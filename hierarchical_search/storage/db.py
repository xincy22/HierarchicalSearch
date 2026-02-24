from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import bindparam, create_engine, delete, event, inspect, insert, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from .models import Base, Document, Section


@dataclass(slots=True)
class SectionRow:
    doc_id: int
    section_id: str
    level: int
    title_text: str
    body_text: str
    heading_raw: str | None
    heading_prefix_raw: str | None
    start_pos: int | None
    end_pos: int | None


class Database:
    def __init__(self, database_url: str):
        self.engine = create_engine(database_url, future=True)
        if self.engine.dialect.name == "sqlite":
            event.listen(self.engine, "connect", self._set_sqlite_pragma)
        self._session_factory = sessionmaker(
            bind=self.engine, expire_on_commit=False, class_=Session
        )

    def create_tables(self) -> None:
        Base.metadata.create_all(self.engine)
        self.ensure_schema()

    @staticmethod
    def _set_sqlite_pragma(dbapi_connection, connection_record) -> None:  # type: ignore[no-untyped-def]
        # Ensure ON DELETE CASCADE works on SQLite.
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    def ensure_schema(self) -> None:
        """Best-effort schema migrations for lightweight local usage.

        This project intentionally avoids Alembic. We only patch forward for
        additive changes that the app depends on (e.g., `documents.doc_key`).
        """

        inspector = inspect(self.engine)
        if "documents" not in inspector.get_table_names():
            return

        doc_columns = {col["name"] for col in inspector.get_columns("documents")}
        needs_doc_key = "doc_key" not in doc_columns

        with self.engine.begin() as conn:
            if needs_doc_key:
                dialect = self.engine.dialect.name
                if dialect == "postgresql":
                    conn.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS doc_key VARCHAR(512)"))
                else:
                    conn.execute(text("ALTER TABLE documents ADD COLUMN doc_key VARCHAR(512)"))

                # Backfill from legacy `filename`.
                conn.execute(
                    text("UPDATE documents SET doc_key = filename WHERE doc_key IS NULL OR doc_key = ''")
                )

            # Deduplicate any legacy rows that would violate the unique index.
            duplicates = conn.execute(
                text(
                    """
                    SELECT doc_key, MIN(doc_id) AS keep_id
                    FROM documents
                    WHERE doc_key IS NOT NULL AND doc_key != ''
                    GROUP BY doc_key
                    HAVING COUNT(*) > 1
                    """
                )
            ).fetchall()
            for doc_key, keep_id in duplicates:
                other_ids = [
                    row[0]
                    for row in conn.execute(
                        text(
                            "SELECT doc_id FROM documents WHERE doc_key = :doc_key AND doc_id != :keep_id"
                        ),
                        {"doc_key": doc_key, "keep_id": keep_id},
                    ).fetchall()
                ]
                if not other_ids:
                    continue
                # Delete children explicitly to be robust even when FK cascades are off.
                conn.execute(
                    text("DELETE FROM sections WHERE doc_id IN :ids").bindparams(
                        bindparam("ids", expanding=True)
                    ),
                    {"ids": other_ids},
                )
                conn.execute(
                    text("DELETE FROM documents WHERE doc_id IN :ids").bindparams(
                        bindparam("ids", expanding=True)
                    ),
                    {"ids": other_ids},
                )

            # Ensure unique index exists.
            existing_indexes = {idx.get("name") for idx in inspector.get_indexes("documents")}
            if "ux_documents_doc_key" not in existing_indexes:
                dialect = self.engine.dialect.name
                if dialect in {"sqlite", "postgresql"}:
                    conn.execute(
                        text(
                            "CREATE UNIQUE INDEX IF NOT EXISTS ux_documents_doc_key ON documents(doc_key)"
                        )
                    )
                else:
                    # MySQL doesn't support IF NOT EXISTS for indexes.
                    conn.execute(
                        text("CREATE UNIQUE INDEX ux_documents_doc_key ON documents(doc_key)")
                    )

    def session(self) -> Session:
        return self._session_factory()

    def healthcheck(self) -> None:
        with self.engine.connect() as conn:
            conn.execute(text("SELECT 1"))

    def dispose(self) -> None:
        self.engine.dispose()


class DocumentRepository:
    def __init__(self, db: Database):
        self.db = db

    def create_document(
        self,
        filename: str,
        file_topic: str,
        doc_title: str | None = None,
        doc_key: str | None = None,
    ) -> int:
        doc_key = (doc_key or filename).strip() or filename
        with self.db.session() as session:
            existing = session.scalars(select(Document).where(Document.doc_key == doc_key).limit(1)).first()
            if existing:
                existing.filename = filename
                existing.file_topic = file_topic
                existing.doc_title = doc_title
                session.commit()
                return existing.doc_id

            row = Document(doc_key=doc_key, filename=filename, file_topic=file_topic, doc_title=doc_title)
            session.add(row)
            try:
                session.commit()
                return row.doc_id
            except IntegrityError:
                session.rollback()
                # Another writer may have inserted the same doc_key.
                existing = session.scalars(select(Document).where(Document.doc_key == doc_key).limit(1)).first()
                if existing:
                    existing.filename = filename
                    existing.file_topic = file_topic
                    existing.doc_title = doc_title
                    session.commit()
                    return existing.doc_id
                raise

    def get_document(self, doc_id: int) -> Document | None:
        with self.db.session() as session:
            return session.get(Document, doc_id)

    def replace_sections(self, doc_id: int, rows: Iterable[SectionRow]) -> None:
        rows = list(rows)
        with self.db.session() as session:
            session.execute(delete(Section).where(Section.doc_id == doc_id))
            if rows:
                payloads = [
                    {
                        "doc_id": row.doc_id,
                        "section_id": row.section_id,
                        "level": row.level,
                        "title_text": row.title_text,
                        "body_text": row.body_text,
                        "heading_raw": row.heading_raw,
                        "heading_prefix_raw": row.heading_prefix_raw,
                        "start_pos": row.start_pos,
                        "end_pos": row.end_pos,
                    }
                    for row in rows
                ]
                session.execute(insert(Section.__table__), payloads)
            session.commit()

    def upsert_sections(self, rows: Iterable[SectionRow]) -> None:
        rows = list(rows)
        if not rows:
            return
        doc_id = rows[0].doc_id
        with self.db.session() as session:
            for row in rows:
                session.merge(
                    Section(
                        doc_id=row.doc_id,
                        section_id=row.section_id,
                        level=row.level,
                        title_text=row.title_text,
                        body_text=row.body_text,
                        heading_raw=row.heading_raw,
                        heading_prefix_raw=row.heading_prefix_raw,
                        start_pos=row.start_pos,
                        end_pos=row.end_pos,
                    )
                )
            session.commit()

            # If section ids changed across re-ingestions, remove stale rows for the doc.
            valid_ids = {row.section_id for row in rows}
            stale = session.scalars(
                select(Section).where(
                    Section.doc_id == doc_id, Section.section_id.not_in(valid_ids)
                )
            ).all()
            for item in stale:
                session.delete(item)
            session.commit()

    def section_exists(self, doc_id: int, section_id: str) -> bool:
        with self.db.session() as session:
            stmt = (
                select(Section.section_id)
                .where(Section.doc_id == doc_id, Section.section_id == section_id)
                .limit(1)
            )
            return session.execute(stmt).first() is not None

    def get_section(self, doc_id: int, section_id: str) -> Section | None:
        with self.db.session() as session:
            stmt = select(Section).where(
                Section.doc_id == doc_id, Section.section_id == section_id
            )
            return session.scalars(stmt).first()

    def list_sections(self, doc_id: int) -> list[Section]:
        with self.db.session() as session:
            stmt = (
                select(Section)
                .where(Section.doc_id == doc_id)
                .order_by(Section.start_pos.asc().nulls_last(), Section.section_id.asc())
            )
            return list(session.scalars(stmt).all())
