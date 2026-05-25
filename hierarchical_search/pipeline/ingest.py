"""入库流水线：markdown → documents + sections + vectors。"""

from __future__ import annotations

from pathlib import Path
import re

from ..parsing.markdown import Section, parse_markdown
from ..storage.db import DocStore
from ..storage.vectors import DocVector, SectionVector, VectorStore
from .embedding import HashingEmbedder


def _extract_topic(markdown: str, filename: str) -> str:
    """简单规则抽取文档主题。"""
    for line in markdown.splitlines():
        line = line.strip()
        if line.startswith("#"):
            return line.lstrip("#").strip()[:120]
    return Path(filename).stem


def _generate_aliases(filename: str, file_topic: str, doc_title: str) -> list[str]:
    """从文件名/主题/标题中拆出检索别名。"""
    tokens: list[str] = []
    for text in (filename, file_topic, doc_title):
        for token in re.split(r"[\s_\-./|，,：:]+", text):
            token = token.strip()
            if len(token) >= 2:
                tokens.append(token)
    seen: set[str] = set()
    dedup: list[str] = []
    for t in tokens:
        low = t.lower()
        if low not in seen:
            seen.add(low)
            dedup.append(t)
    return dedup[:8]


def _section_vector_text(s: Section) -> str:
    """按方案 4.4：只放层级标题拼接，不放 doc 信息。"""
    if s.level <= 1:
        return s.l1_title or s.title_text
    if s.level == 2:
        return "\n".join(x for x in (s.l1_title, s.l2_title) if x).strip()
    return "\n".join(x for x in (s.l1_title, s.l2_title, s.l3_title) if x).strip()


def ingest_markdown(
    markdown: str,
    filename: str,
    doc_key: str,
    embedder: HashingEmbedder,
    doc_store: DocStore,
    vector_store: VectorStore,
) -> int:
    """入库一篇 markdown，返回 doc_id。"""
    sections = parse_markdown(markdown)
    file_topic = _extract_topic(markdown, filename)
    doc_title = next(
        (s.title_text for s in sections if s.level == 1 and s.title_text.strip()),
        Path(filename).stem,
    )

    # 写 documents
    doc_id = doc_store.upsert_document(doc_key, filename, file_topic, doc_title)

    # 写 sections
    doc_store.replace_sections(
        doc_id,
        [(s.section_id, s.level, s.title_text, s.body_text) for s in sections],
    )

    # doc_vectors：base + aliases（方案 6.1）
    base_text = f"{filename}\n{file_topic}\n{doc_title}"
    aliases = _generate_aliases(filename, file_topic, doc_title)
    doc_texts = [base_text] + [f"{a}\n{doc_title}\n{file_topic}" for a in aliases]
    doc_vecs = embedder.embed_many(doc_texts)
    vector_store.add_doc_vectors(
        doc_id,
        [DocVector(doc_id=doc_id, text=t, vector=v) for t, v in zip(doc_texts, doc_vecs)],
    )

    # section_vectors（方案 4.4）
    sec_texts = [_section_vector_text(s) for s in sections]
    sec_vecs = embedder.embed_many(sec_texts)
    vector_store.add_section_vectors(
        doc_id,
        [
            SectionVector(doc_id=doc_id, section_id=s.section_id, text=t, vector=v)
            for s, t, v in zip(sections, sec_texts, sec_vecs)
        ],
    )

    return doc_id


def ingest_file(
    path: str,
    embedder: HashingEmbedder,
    doc_store: DocStore,
    vector_store: VectorStore,
) -> int:
    p = Path(path)
    content = p.read_text(encoding="utf-8")
    # 优先用相对 cwd 的路径作为 doc_key（保持原有行为）；
    # 路径在 cwd 之外（例如临时目录、绝对路径）时退回 absolute posix。
    abs_p = p.resolve()
    try:
        doc_key = abs_p.relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        doc_key = abs_p.as_posix()
    return ingest_markdown(content, p.name, doc_key, embedder, doc_store, vector_store)
