from __future__ import annotations

from dataclasses import dataclass, field
from dataclasses import asdict
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
        count_map: dict[int, int] = {}
        text_map: dict[int, str] = {}
        for hit in hits:
            raw_doc_id = hit.payload.get("doc_id")
            if raw_doc_id is None:
                continue
            doc_id = int(raw_doc_id)
            if hit.score > score_map.get(doc_id, float("-inf")):
                score_map[doc_id] = hit.score
                text_map[doc_id] = str(hit.payload.get("text", ""))
            count_map[doc_id] = count_map.get(doc_id, 0) + 1
        candidates = [
            DocCandidate(
                doc_id=doc_id,
                score=score,
                notes=f"{text_map.get(doc_id, '')}\nvariants={count_map[doc_id]}",
            )
            for doc_id, score in score_map.items()
        ]
        candidates.sort(key=lambda x: x.score, reverse=True)
        return candidates

    @staticmethod
    def _should_rerank(candidates: list[DocCandidate] | list[SectionCandidate], gap_threshold: float) -> bool:
        if len(candidates) <= 1:
            return False
        gap = candidates[0].score - candidates[1].score
        return gap < gap_threshold

    @staticmethod
    def _merge_doc_ranking(
        original: list[DocCandidate],
        reranked: list[DocCandidate],
    ) -> list[DocCandidate]:
        used = {x.doc_id for x in reranked}
        tail = [x for x in original if x.doc_id not in used]
        return reranked + tail

    @staticmethod
    def _merge_section_ranking(
        original: list[SectionCandidate],
        reranked: list[SectionCandidate],
    ) -> list[SectionCandidate]:
        used = {x.section_id for x in reranked}
        tail = [x for x in original if x.section_id not in used]
        return reranked + tail

    @staticmethod
    def _aggregate_section_hits(hits: list[SearchHit]) -> list[SectionCandidate]:
        score_map: dict[str, float] = {}
        text_map: dict[str, str] = {}
        for hit in hits:
            raw = hit.payload.get("section_id")
            if raw is None:
                continue
            section_id = str(raw)
            if hit.score > score_map.get(section_id, float("-inf")):
                score_map[section_id] = hit.score
                text_map[section_id] = "\n".join(
                    str(hit.payload.get(k, "")) for k in ("text", "l1_title", "l2_title", "l3_title")
                ).strip()
        candidates = [
            SectionCandidate(section_id=section_id, score=score, notes=text_map.get(section_id, ""))
            for section_id, score in score_map.items()
        ]
        candidates.sort(key=lambda x: x.score, reverse=True)
        return candidates

    def retrieve(self, query: str) -> RetrievalResult:
        diagnostics: dict[str, object] = {"query": query}
        query_vec = self.embedder.embed_text(query)

        # Step 1: doc_id from doc_vectors.
        doc_hits = self.vector_store.search_doc_vectors(query_vec, self.settings.doc_top_k)
        if not doc_hits:
            return RetrievalResult(
                found=False,
                diagnostics={**diagnostics, "error": "doc_vectors_empty"},
            )

        doc_candidates = self._aggregate_doc_hits(doc_hits)
        if not doc_candidates:
            return RetrievalResult(
                found=False,
                diagnostics={**diagnostics, "error": "doc_aggregation_empty"},
            )
        # Local lexical rerank is cheap and improves numeric hash-vector tie cases.
        doc_candidates = self._local_reranker.rerank_doc_candidates(query, doc_candidates)
        if self.settings.llm_rerank_enabled and self._should_rerank(
            doc_candidates, self.settings.doc_rerank_gap_threshold
        ):
            limit = max(1, self.settings.doc_rerank_max_candidates)
            reranked = self.llm.rerank_doc_candidates(query, doc_candidates[:limit])
            doc_candidates = self._merge_doc_ranking(doc_candidates, reranked)
        diagnostics["doc_candidates"] = [asdict(candidate) for candidate in doc_candidates[:5]]
        skipped_missing_docs: list[int] = []
        selected_doc: DocCandidate | None = None
        for candidate in doc_candidates:
            if self.repository.get_document(candidate.doc_id):
                selected_doc = candidate
                break
            skipped_missing_docs.append(candidate.doc_id)
        if skipped_missing_docs:
            diagnostics["skipped_missing_docs"] = skipped_missing_docs
        if selected_doc is None:
            return RetrievalResult(
                found=False,
                diagnostics={**diagnostics, "error": "all_doc_candidates_missing"},
            )
        selected_doc_id = selected_doc.doc_id

        # Step 2: anchor parse via LLM.
        anchor_section_id = self.llm.resolve_section_id(query)
        diagnostics["anchor_section_id"] = anchor_section_id
        normalized_anchor = (
            normalize_section_id(anchor_section_id)
            if anchor_section_id != INSUFFICIENT
            else None
        )

        # Step 3: existence check.
        if normalized_anchor and re.fullmatch(r"\d+(?:\.\d+)*", normalized_anchor):
            if self.repository.section_exists(selected_doc_id, normalized_anchor):
                section = self.repository.get_section(selected_doc_id, normalized_anchor)
                if section:
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
                diagnostics["anchor_exists_but_read_failed"] = True
            diagnostics["anchor_exists"] = False

        # Step 4: section vector fallback (doc-filtered).
        section_hits = self.vector_store.search_section_vectors(
            query_vector=query_vec,
            doc_id=selected_doc_id,
            top_k=self.settings.section_top_k,
        )
        if not section_hits:
            return RetrievalResult(
                found=False,
                doc_id=selected_doc_id,
                doc_method="doc_vectors+rerank",
                section_method="fallback_vectors",
                diagnostics={**diagnostics, "error": "section_vectors_empty"},
            )
        section_candidates = self._aggregate_section_hits(section_hits)
        # Apply lexical rerank before optional LLM rerank for better robustness.
        section_candidates = self._local_reranker.rerank_section_candidates(query, section_candidates)
        if self.settings.llm_rerank_enabled and self._should_rerank(
            section_candidates, self.settings.section_rerank_gap_threshold
        ):
            limit = max(1, self.settings.section_rerank_max_candidates)
            reranked = self.llm.rerank_section_candidates(query, section_candidates[:limit])
            section_candidates = self._merge_section_ranking(section_candidates, reranked)
        diagnostics["section_candidates"] = [asdict(c) for c in section_candidates[:5]]
        if not section_candidates:
            return RetrievalResult(
                found=False,
                doc_id=selected_doc_id,
                doc_method="doc_vectors+rerank",
                section_method="fallback_vectors",
                diagnostics={**diagnostics, "error": "section_candidates_empty"},
            )

        selected_section_id = section_candidates[0].section_id
        section = self.repository.get_section(selected_doc_id, selected_section_id)
        if not section:
            return RetrievalResult(
                found=False,
                doc_id=selected_doc_id,
                section_id=selected_section_id,
                doc_method="doc_vectors+rerank",
                section_method="fallback_vectors",
                diagnostics={**diagnostics, "error": "section_row_missing"},
            )

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
