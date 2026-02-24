from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import create_engine, select, text
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
        self._session_factory = sessionmaker(
            bind=self.engine, expire_on_commit=False, class_=Session
        )

    def create_tables(self) -> None:
        Base.metadata.create_all(self.engine)

    def session(self) -> Session:
        return self._session_factory()

    def healthcheck(self) -> None:
        with self.engine.connect() as conn:
            conn.execute(text("SELECT 1"))


class DocumentRepository:
    def __init__(self, db: Database):
        self.db = db

    def create_document(
        self, filename: str, file_topic: str, doc_title: str | None = None
    ) -> int:
        with self.db.session() as session:
            existing = session.scalars(
                select(Document)
                .where(Document.filename == filename)
                .order_by(Document.doc_id.asc())
                .limit(1)
            ).first()
            if existing:
                existing.file_topic = file_topic
                existing.doc_title = doc_title
                session.query(Section).where(Section.doc_id == existing.doc_id).delete()
                # Keep a single stable doc_id per filename.
                duplicates = session.scalars(
                    select(Document).where(
                        Document.filename == filename, Document.doc_id != existing.doc_id
                    )
                ).all()
                for duplicate in duplicates:
                    session.delete(duplicate)
                session.commit()
                return existing.doc_id

            row = Document(filename=filename, file_topic=file_topic, doc_title=doc_title)
            session.add(row)
            session.commit()
            return row.doc_id

    def get_document(self, doc_id: int) -> Document | None:
        with self.db.session() as session:
            return session.get(Document, doc_id)

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
