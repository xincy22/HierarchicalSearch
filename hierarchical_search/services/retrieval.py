from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re

from ..ai.embedding import Embedder
from ..ai.llm import DocCandidate, LLMClient, RuleBasedLLMClient, SectionCandidate
from ..app.config import Settings
from ..parsers.anchor import INSUFFICIENT, normalize_section_id
from ..storage.db import DocumentRepository
from ..storage.vector_store.base import SearchHit, VectorStore


@dataclass(slots=True)
class RetrievalResult:
    found: bool
    doc_id: int | None = None
    section_id: str | None = None
    title_text: str | None = None
    body_text: str | None = None
    doc_method: str = ""
    section_method: str = ""
    diagnostics: dict[str, object] = field(default_factory=dict)


class HierarchicalRetriever:
    def __init__(
        self,
        settings: Settings,
        repository: DocumentRepository,
        vector_store: VectorStore,
        embedder: Embedder,
        llm_client: LLMClient,
    ):
        self.settings = settings
        self.repository = repository
        self.vector_store = vector_store
        self.embedder = embedder
        self.llm = llm_client
        self._local_reranker = RuleBasedLLMClient()

    @staticmethod
    def _aggregate_doc_hits(hits: list[SearchHit]) -> list[DocCandidate]:
        score_map: dict[int, float] = {}
        text_map: dict[int, str] = {}
        for hit in hits:
            doc_id = int(hit.payload["doc_id"])
            if hit.score > score_map.get(doc_id, float("-inf")):
                score_map[doc_id] = hit.score
                text_map[doc_id] = str(hit.payload.get("text", ""))
        candidates = [
            DocCandidate(doc_id=doc_id, score=score, notes=text_map[doc_id])
            for doc_id, score in score_map.items()
        ]
        candidates.sort(key=lambda x: x.score, reverse=True)
        return candidates

    @staticmethod
    def _aggregate_section_hits(hits: list[SearchHit]) -> list[SectionCandidate]:
        score_map: dict[str, float] = {}
        text_map: dict[str, str] = {}
        for hit in hits:
            section_id = str(hit.payload["section_id"])
            if hit.score > score_map.get(section_id, float("-inf")):
                score_map[section_id] = hit.score
                text_map[section_id] = "\n".join(
                    str(hit.payload.get(k, ""))
                    for k in ("text", "l1_title", "l2_title", "l3_title")
                ).strip()
        candidates = [
            SectionCandidate(section_id=sid, score=score, notes=text_map[sid])
            for sid, score in score_map.items()
        ]
        candidates.sort(key=lambda x: x.score, reverse=True)
        return candidates

    def retrieve(self, query: str) -> RetrievalResult:
        diagnostics: dict[str, object] = {"query": query}
        query_vec = self.embedder.embed_text(query)

        # Step 1: doc_id from doc_vectors.
        doc_hits = self.vector_store.search_doc_vectors(query_vec, self.settings.doc_top_k)
        doc_candidates = self._aggregate_doc_hits(doc_hits)
        doc_candidates = self._local_reranker.rerank_doc_candidates(query, doc_candidates)
        if self.settings.llm_rerank_enabled:
            doc_candidates = self.llm.rerank_doc_candidates(query, doc_candidates)
        diagnostics["doc_candidates"] = [asdict(c) for c in doc_candidates[:5]]
        selected_doc_id = doc_candidates[0].doc_id

        # Step 2: anchor parse via LLM.
        anchor_section_id = self.llm.resolve_section_id(query)
        diagnostics["anchor_section_id"] = anchor_section_id

        # Step 3: existence check.
        if anchor_section_id != INSUFFICIENT:
            normalized_anchor = normalize_section_id(anchor_section_id)
            if normalized_anchor and re.fullmatch(r"\d+(?:\.\d+)*", normalized_anchor):
                if self.repository.section_exists(selected_doc_id, normalized_anchor):
                    section = self.repository.get_section(selected_doc_id, normalized_anchor)
                    return RetrievalResult(
                        found=True,
                        doc_id=selected_doc_id,
                        section_id=normalized_anchor,
                        title_text=section.title_text,
                        body_text=section.body_text,
                        doc_method="doc_vectors+rerank",
                        section_method="anchor_exact",
                        diagnostics=diagnostics,
                    )

        # Step 4: section vector fallback.
        section_hits = self.vector_store.search_section_vectors(
            query_vector=query_vec,
            doc_id=selected_doc_id,
            top_k=self.settings.section_top_k,
        )
        section_candidates = self._aggregate_section_hits(section_hits)
        section_candidates = self._local_reranker.rerank_section_candidates(
            query, section_candidates
        )
        if self.settings.llm_rerank_enabled:
            section_candidates = self.llm.rerank_section_candidates(query, section_candidates)
        diagnostics["section_candidates"] = [asdict(c) for c in section_candidates[:5]]

        selected_section_id = section_candidates[0].section_id
        section = self.repository.get_section(selected_doc_id, selected_section_id)

        # Step 5: return body_text.
        return RetrievalResult(
            found=True,
            doc_id=selected_doc_id,
            section_id=selected_section_id,
            title_text=section.title_text,
            body_text=section.body_text,
            doc_method="doc_vectors+rerank",
            section_method="fallback_vectors",
            diagnostics=diagnostics,
        )
