from __future__ import annotations

from dataclasses import asdict
import math

from .base import DocVectorRecord, SearchHit, SectionVectorRecord


def _dot(a: list[float], b: list[float]) -> float:
    return float(sum(x * y for x, y in zip(a, b)))


def _norm(a: list[float]) -> float:
    return math.sqrt(_dot(a, a))


def _cosine(a: list[float], b: list[float]) -> float:
    an = _norm(a)
    bn = _norm(b)
    if an == 0 or bn == 0:
        return 0.0
    return _dot(a, b) / (an * bn)


class InMemoryVectorStore:
    """Local vector backend for dev/test. Interface-compatible with Milvus backend."""

    def __init__(self):
        self._doc_rows: list[dict[str, object]] = []
        self._section_rows: list[dict[str, object]] = []

    def add_doc_vectors(self, rows: list[DocVectorRecord]) -> None:
        if not rows:
            return
        doc_ids = {row.doc_id for row in rows}
        self._doc_rows = [row for row in self._doc_rows if row["doc_id"] not in doc_ids]
        self._doc_rows.extend(asdict(row) for row in rows)

    def add_section_vectors(self, rows: list[SectionVectorRecord]) -> None:
        if not rows:
            return
        doc_ids = {row.doc_id for row in rows}
        self._section_rows = [
            row for row in self._section_rows if row["doc_id"] not in doc_ids
        ]
        self._section_rows.extend(asdict(row) for row in rows)

    def search_doc_vectors(self, query_vector: list[float], top_k: int) -> list[SearchHit]:
        scored = [
            SearchHit(score=_cosine(query_vector, row["vector"]), payload=row)
            for row in self._doc_rows
        ]
        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[:top_k]

    def search_section_vectors(
        self, query_vector: list[float], doc_id: int, top_k: int
    ) -> list[SearchHit]:
        rows = [row for row in self._section_rows if row["doc_id"] == doc_id]
        scored = [
            SearchHit(score=_cosine(query_vector, row["vector"]), payload=row) for row in rows
        ]
        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[:top_k]
