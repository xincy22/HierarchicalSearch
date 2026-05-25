"""内存向量存储：doc_vectors + section_vectors。

可选地将向量持久化到与 DocStore 共用的 SQLite，便于 CLI 跨进程查询。
持久化为可选能力，库用法保持纯内存。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .db import DocStore


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

    # --- 持久化（可选）---
    #
    # 设计取舍：
    # - 不引入向量库依赖；JSON 存 list[float]，文档量小够用。
    # - 与 DocStore 共用 connection，事务边界跟随 DocStore 的 commit。
    # - persist_to/load_from 是显式动作，调用方决定何时落盘 / 何时加载。

    def persist_to(self, doc_store: "DocStore") -> None:
        """把当前内存向量整体写入 SQLite。先建表后整表替换。"""
        conn = doc_store.conn
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS doc_vectors (
                doc_id INTEGER NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
                idx INTEGER NOT NULL,
                text TEXT NOT NULL,
                vector_json TEXT NOT NULL,
                PRIMARY KEY (doc_id, idx)
            );
            CREATE TABLE IF NOT EXISTS section_vectors (
                doc_id INTEGER NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
                section_id TEXT NOT NULL,
                text TEXT NOT NULL,
                vector_json TEXT NOT NULL,
                PRIMARY KEY (doc_id, section_id)
            );
        """)
        conn.execute("DELETE FROM doc_vectors")
        conn.execute("DELETE FROM section_vectors")

        # doc_vectors 在内存里同 doc_id 有多条（base + aliases），用 idx 去重
        per_doc_idx: dict[int, int] = {}
        rows: list[tuple[int, int, str, str]] = []
        for v in self.doc_vectors:
            i = per_doc_idx.get(v.doc_id, 0)
            per_doc_idx[v.doc_id] = i + 1
            rows.append((v.doc_id, i, v.text, json.dumps(v.vector)))
        conn.executemany(
            "INSERT INTO doc_vectors(doc_id, idx, text, vector_json) VALUES(?,?,?,?)",
            rows,
        )

        sec_rows = [
            (v.doc_id, v.section_id, v.text, json.dumps(v.vector))
            for v in self.section_vectors
        ]
        conn.executemany(
            "INSERT INTO section_vectors(doc_id, section_id, text, vector_json)"
            " VALUES(?,?,?,?)",
            sec_rows,
        )
        conn.commit()

    def load_from(self, doc_store: "DocStore") -> None:
        """从 SQLite 读回向量到内存，覆盖当前内存内容。"""
        conn = doc_store.conn
        # 表可能尚未创建（首次使用 query 但没 ingest 过）
        has_doc = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='doc_vectors'"
        ).fetchone()
        has_sec = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='section_vectors'"
        ).fetchone()
        self.doc_vectors = []
        self.section_vectors = []
        if has_doc:
            for row in conn.execute(
                "SELECT doc_id, text, vector_json FROM doc_vectors ORDER BY doc_id, idx"
            ):
                self.doc_vectors.append(
                    DocVector(
                        doc_id=row["doc_id"],
                        text=row["text"],
                        vector=json.loads(row["vector_json"]),
                    )
                )
        if has_sec:
            for row in conn.execute(
                "SELECT doc_id, section_id, text, vector_json FROM section_vectors"
            ):
                self.section_vectors.append(
                    SectionVector(
                        doc_id=row["doc_id"],
                        section_id=row["section_id"],
                        text=row["text"],
                        vector=json.loads(row["vector_json"]),
                    )
                )
