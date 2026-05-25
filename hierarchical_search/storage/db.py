"""SQLite 存储：documents + sections。"""

from __future__ import annotations

import sqlite3


def _init_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS documents (
            doc_id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_key TEXT UNIQUE NOT NULL,
            filename TEXT NOT NULL,
            file_topic TEXT NOT NULL,
            doc_title TEXT
        );
        CREATE TABLE IF NOT EXISTS sections (
            doc_id INTEGER NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
            section_id TEXT NOT NULL,
            level INTEGER NOT NULL,
            title_text TEXT NOT NULL,
            body_text TEXT NOT NULL,
            PRIMARY KEY (doc_id, section_id)
        );
    """)
    conn.commit()
    return conn


class DocStore:
    def __init__(self, db_path: str = "hierarchical_search.db"):
        self.conn = _init_db(db_path)

    def upsert_document(
        self, doc_key: str, filename: str, file_topic: str, doc_title: str
    ) -> int:
        row = self.conn.execute(
            "SELECT doc_id FROM documents WHERE doc_key = ?", (doc_key,)
        ).fetchone()
        if row:
            doc_id = row["doc_id"]
            self.conn.execute(
                "UPDATE documents SET filename=?, file_topic=?, doc_title=? WHERE doc_id=?",
                (filename, file_topic, doc_title, doc_id),
            )
        else:
            cur = self.conn.execute(
                "INSERT INTO documents(doc_key, filename, file_topic, doc_title) VALUES(?,?,?,?)",
                (doc_key, filename, file_topic, doc_title),
            )
            doc_id = cur.lastrowid
        self.conn.commit()
        return doc_id

    def replace_sections(
        self, doc_id: int, sections: list[tuple[str, int, str, str]]
    ) -> None:
        """sections: list of (section_id, level, title_text, body_text)"""
        self.conn.execute("DELETE FROM sections WHERE doc_id = ?", (doc_id,))
        self.conn.executemany(
            "INSERT INTO sections(doc_id, section_id, level, title_text, body_text) VALUES(?,?,?,?,?)",
            [(doc_id, sid, lvl, title, body) for sid, lvl, title, body in sections],
        )
        self.conn.commit()

    def section_exists(self, doc_id: int, section_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM sections WHERE doc_id=? AND section_id=? LIMIT 1",
            (doc_id, section_id),
        ).fetchone()
        return row is not None

    def get_section(self, doc_id: int, section_id: str) -> tuple[str, str] | None:
        """Returns (title_text, body_text) or None."""
        row = self.conn.execute(
            "SELECT title_text, body_text FROM sections WHERE doc_id=? AND section_id=?",
            (doc_id, section_id),
        ).fetchone()
        if row:
            return (row["title_text"], row["body_text"])
        return None
