from __future__ import annotations

import json
import math
import sqlite3

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


class SQLiteVectorStore:
    """Persistent local vector backend for development and CI."""

    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS doc_vectors (
                doc_id INTEGER NOT NULL,
                variant TEXT NOT NULL,
                text TEXT NOT NULL,
                vector TEXT NOT NULL
            );
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS section_vectors (
                doc_id INTEGER NOT NULL,
                section_id TEXT NOT NULL,
                l1_title TEXT,
                l2_title TEXT,
                l3_title TEXT,
                text TEXT NOT NULL,
                vector TEXT NOT NULL
            );
            """
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_doc_vectors_doc_id ON doc_vectors(doc_id);"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_section_vectors_doc_id ON section_vectors(doc_id);"
        )
        self.conn.commit()

    def add_doc_vectors(self, rows: list[DocVectorRecord]) -> None:
        if not rows:
            return
        doc_ids = sorted({r.doc_id for r in rows})
        placeholders = ",".join("?" for _ in doc_ids)
        self.conn.execute(
            f"DELETE FROM doc_vectors WHERE doc_id IN ({placeholders})", tuple(doc_ids)
        )
        self.conn.executemany(
            """
            INSERT INTO doc_vectors(doc_id, variant, text, vector)
            VALUES (?, ?, ?, ?)
            """,
            [
                (
                    row.doc_id,
                    row.variant,
                    row.text,
                    json.dumps(row.vector, ensure_ascii=False),
                )
                for row in rows
            ],
        )
        self.conn.commit()

    def add_section_vectors(self, rows: list[SectionVectorRecord]) -> None:
        if not rows:
            return
        doc_ids = sorted({r.doc_id for r in rows})
        placeholders = ",".join("?" for _ in doc_ids)
        self.conn.execute(
            f"DELETE FROM section_vectors WHERE doc_id IN ({placeholders})", tuple(doc_ids)
        )
        self.conn.executemany(
            """
            INSERT INTO section_vectors(doc_id, section_id, l1_title, l2_title, l3_title, text, vector)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    row.doc_id,
                    row.section_id,
                    row.l1_title,
                    row.l2_title,
                    row.l3_title,
                    row.text,
                    json.dumps(row.vector, ensure_ascii=False),
                )
                for row in rows
            ],
        )
        self.conn.commit()

    def search_doc_vectors(self, query_vector: list[float], top_k: int) -> list[SearchHit]:
        rows = self.conn.execute("SELECT doc_id, variant, text, vector FROM doc_vectors").fetchall()
        hits: list[SearchHit] = []
        for row in rows:
            vector = json.loads(row["vector"])
            score = _cosine(query_vector, vector)
            hits.append(
                SearchHit(
                    score=score,
                    payload={
                        "doc_id": row["doc_id"],
                        "variant": row["variant"],
                        "text": row["text"],
                        "vector": vector,
                    },
                )
            )
        hits.sort(key=lambda x: x.score, reverse=True)
        return hits[:top_k]

    def search_section_vectors(
        self, query_vector: list[float], doc_id: int, top_k: int
    ) -> list[SearchHit]:
        rows = self.conn.execute(
            """
            SELECT doc_id, section_id, l1_title, l2_title, l3_title, text, vector
            FROM section_vectors
            WHERE doc_id = ?
            """,
            (doc_id,),
        ).fetchall()
        hits: list[SearchHit] = []
        for row in rows:
            vector = json.loads(row["vector"])
            score = _cosine(query_vector, vector)
            hits.append(
                SearchHit(
                    score=score,
                    payload={
                        "doc_id": row["doc_id"],
                        "section_id": row["section_id"],
                        "l1_title": row["l1_title"],
                        "l2_title": row["l2_title"],
                        "l3_title": row["l3_title"],
                        "text": row["text"],
                        "vector": vector,
                    },
                )
            )
        hits.sort(key=lambda x: x.score, reverse=True)
        return hits[:top_k]
