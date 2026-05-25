from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import create_engine, delete, event, insert, select
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

    @staticmethod
    def _set_sqlite_pragma(dbapi_connection, connection_record) -> None:  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    def session(self) -> Session:
        return self._session_factory()

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
            existing = session.scalars(
                select(Document).where(Document.doc_key == doc_key).limit(1)
            ).first()
            if existing:
                existing.filename = filename
                existing.file_topic = file_topic
                existing.doc_title = doc_title
                session.commit()
                return existing.doc_id
            row = Document(
                doc_key=doc_key,
                filename=filename,
                file_topic=file_topic,
                doc_title=doc_title,
            )
            session.add(row)
            session.commit()
            return row.doc_id

    def get_document(self, doc_id: int) -> Document | None:
        with self.db.session() as session:
            return session.get(Document, doc_id)

    def replace_sections(self, doc_id: int, rows: Iterable[SectionRow]) -> None:
        rows = list(rows)
        with self.db.session() as session:
            session.execute(delete(Section).where(Section.doc_id == doc_id))
            if rows:
                session.execute(
                    insert(Section.__table__),
                    [
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
                    ],
                )
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
