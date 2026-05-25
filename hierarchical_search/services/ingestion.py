from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..ai.embedding import Embedder
from ..ai.llm import LLMClient
from ..parsers.markdown import MarkdownSectionParser, ParsedSection
from ..storage.db import DocumentRepository, SectionRow
from ..storage.vector_store.base import DocVectorRecord, SectionVectorRecord, VectorStore


@dataclass(slots=True)
class IngestionResult:
    doc_id: int
    section_count: int
    doc_vector_count: int
    section_vector_count: int


def _guess_doc_title(filename: str, sections: list[ParsedSection]) -> str:
    for item in sections:
        if item.level == 1 and item.title_text.strip():
            return item.title_text.strip()
    return Path(filename).stem or filename


def _section_vector_text(section: ParsedSection) -> str:
    if section.level <= 1:
        return section.l1_title or section.title_text
    if section.level == 2:
        return "\n".join(x for x in (section.l1_title, section.l2_title) if x).strip()
    return "\n".join(
        x for x in (section.l1_title, section.l2_title, section.l3_title) if x
    ).strip()


class IngestionPipeline:
    def __init__(
        self,
        repository: DocumentRepository,
        vector_store: VectorStore,
        embedder: Embedder,
        llm_client: LLMClient,
        parser: MarkdownSectionParser | None = None,
    ):
        self.repository = repository
        self.vector_store = vector_store
        self.embedder = embedder
        self.llm = llm_client
        self.parser = parser or MarkdownSectionParser()

    def ingest_markdown_text(
        self, markdown: str, filename: str, doc_key: str | None = None
    ) -> IngestionResult:
        sections = self.parser.parse(markdown)
        doc_title = _guess_doc_title(filename, sections)
        file_topic = self.llm.extract_topic(markdown, filename)
        normalized_key = (doc_key or filename).replace("\\", "/")
        doc_id = self.repository.create_document(
            doc_key=normalized_key,
            filename=filename,
            file_topic=file_topic,
            doc_title=doc_title,
        )

        aliases = self.llm.generate_aliases(filename, file_topic, doc_title, max_aliases=8)
        base_header = (
            f"{filename}\n{normalized_key}" if normalized_key != filename else filename
        )
        doc_variants: list[tuple[str, str]] = [
            ("base", f"{base_header}\n{file_topic}\n{doc_title}")
        ]
        for idx, alias in enumerate(aliases):
            doc_variants.append((f"alias_{idx + 1}", f"{alias}\n{doc_title}\n{file_topic}"))

        doc_texts = [text for _, text in doc_variants]
        doc_embeddings = self.embedder.embed_texts(doc_texts)
        doc_vectors = [
            DocVectorRecord(
                doc_id=doc_id, variant=variant, text=text, vector=doc_embeddings[idx]
            )
            for idx, (variant, text) in enumerate(doc_variants)
        ]
        self.vector_store.add_doc_vectors(doc_vectors)

        section_rows = [
            SectionRow(
                doc_id=doc_id,
                section_id=s.section_id,
                level=s.level,
                title_text=s.title_text,
                body_text=s.body_text,
                heading_raw=s.heading_raw,
                heading_prefix_raw=s.heading_prefix_raw,
                start_pos=s.start_pos,
                end_pos=s.end_pos,
            )
            for s in sections
        ]
        self.repository.replace_sections(doc_id, section_rows)

        section_texts = [_section_vector_text(s) for s in sections]
        section_embeddings = self.embedder.embed_texts(section_texts)
        section_vectors = [
            SectionVectorRecord(
                doc_id=doc_id,
                section_id=s.section_id,
                l1_title=s.l1_title,
                l2_title=s.l2_title,
                l3_title=s.l3_title,
                text=section_texts[idx],
                vector=section_embeddings[idx],
            )
            for idx, s in enumerate(sections)
        ]
        self.vector_store.add_section_vectors(section_vectors)

        return IngestionResult(
            doc_id=doc_id,
            section_count=len(sections),
            doc_vector_count=len(doc_vectors),
            section_vector_count=len(section_vectors),
        )

    def ingest_markdown_file(self, path: str) -> IngestionResult:
        p = Path(path)
        content = p.read_text(encoding="utf-8")
        doc_key = p.resolve().relative_to(Path.cwd().resolve()).as_posix()
        return self.ingest_markdown_text(content, filename=p.name, doc_key=doc_key)
