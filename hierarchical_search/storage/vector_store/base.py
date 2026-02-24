from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class DocVectorRecord:
    doc_id: int
    vector: list[float]
    text: str
    variant: str = "base"


@dataclass(slots=True)
class SectionVectorRecord:
    doc_id: int
    section_id: str
    vector: list[float]
    text: str
    l1_title: str = ""
    l2_title: str = ""
    l3_title: str = ""


@dataclass(slots=True)
class SearchHit:
    score: float
    payload: dict[str, object]


class VectorStore(Protocol):
    def add_doc_vectors(self, rows: list[DocVectorRecord]) -> None:
        ...

    def add_section_vectors(self, rows: list[SectionVectorRecord]) -> None:
        ...

    def search_doc_vectors(self, query_vector: list[float], top_k: int) -> list[SearchHit]:
        ...

    def search_section_vectors(
        self, query_vector: list[float], doc_id: int, top_k: int
    ) -> list[SearchHit]:
        ...
