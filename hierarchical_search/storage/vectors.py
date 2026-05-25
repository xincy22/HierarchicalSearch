"""内存向量存储：doc_vectors + section_vectors。"""

from __future__ import annotations

import math
from dataclasses import dataclass


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


@dataclass(slots=True)
class DocVector:
    doc_id: int
    text: str
    vector: list[float]


@dataclass(slots=True)
class SectionVector:
    doc_id: int
    section_id: str
    text: str
    vector: list[float]


class VectorStore:
    def __init__(self):
        self.doc_vectors: list[DocVector] = []
        self.section_vectors: list[SectionVector] = []

    def add_doc_vectors(self, doc_id: int, vectors: list[DocVector]) -> None:
        self.doc_vectors = [v for v in self.doc_vectors if v.doc_id != doc_id]
        self.doc_vectors.extend(vectors)

    def add_section_vectors(self, doc_id: int, vectors: list[SectionVector]) -> None:
        self.section_vectors = [v for v in self.section_vectors if v.doc_id != doc_id]
        self.section_vectors.extend(vectors)

    def search_docs(
        self, query_vec: list[float], top_k: int
    ) -> list[tuple[DocVector, float]]:
        scored = [(v, _cosine(query_vec, v.vector)) for v in self.doc_vectors]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def search_sections(
        self, query_vec: list[float], doc_id: int, top_k: int
    ) -> list[tuple[SectionVector, float]]:
        rows = [v for v in self.section_vectors if v.doc_id == doc_id]
        scored = [(v, _cosine(query_vec, v.vector)) for v in rows]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]
