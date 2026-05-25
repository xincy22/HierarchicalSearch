"""在线单链检索：doc_id → section_id（锚点优先，向量兜底）→ body_text。"""

from __future__ import annotations

from dataclasses import dataclass, field
import re

from ..parsing.anchor import INSUFFICIENT, normalize_section_id, parse_anchor
from ..storage.db import DocStore
from ..storage.vectors import VectorStore
from .embedding import HashingEmbedder


@dataclass(slots=True)
class RetrievalResult:
    found: bool
    doc_id: int | None = None
    section_id: str | None = None
    title_text: str | None = None
    body_text: str | None = None
    doc_method: str = ""
    section_method: str = ""
    reject_reason: str | None = None
    diagnostics: dict[str, object] = field(default_factory=dict)


# 默认置信度阈值。低于这些值视为"看似命中实际乱猜"，宁可拒答。
# 数值偏保守，调用方可按需放宽。
DEFAULT_MIN_DOC_SCORE = 0.05
DEFAULT_MIN_DOC_OVERLAP = 1
DEFAULT_MIN_SECTION_SCORE = 0.05
DEFAULT_MIN_SECTION_OVERLAP = 1


# --- rerank（词法重排，方案 7.2/7.5 的最小实现）---


def _tokenize(text: str) -> set[str]:
    tokens: set[str] = set(re.findall(r"[A-Za-z0-9_]+", text.lower()))
    for chunk in re.findall(r"[\u4e00-\u9fff]+", text):
        tokens.add(chunk)
        for i in range(len(chunk) - 1):
            tokens.add(chunk[i : i + 2])
    return tokens


def _lexical_overlap(query: str, text: str) -> int:
    return len(_tokenize(query) & _tokenize(text))


# --- 核心检索 ---


def retrieve(
    query: str,
    embedder: HashingEmbedder,
    doc_store: DocStore,
    vector_store: VectorStore,
    doc_top_k: int = 20,
    section_top_k: int = 50,
    min_doc_score: float = DEFAULT_MIN_DOC_SCORE,
    min_doc_overlap: int = DEFAULT_MIN_DOC_OVERLAP,
    min_section_score: float = DEFAULT_MIN_SECTION_SCORE,
    min_section_overlap: int = DEFAULT_MIN_SECTION_OVERLAP,
) -> RetrievalResult:
    diagnostics: dict[str, object] = {"query": query}
    query_vec = embedder.embed(query)

    # Step 1: doc_vectors 召回 + 按 doc_id 聚合（方案 7.2）
    doc_hits = vector_store.search_docs(query_vec, doc_top_k)
    if not doc_hits:
        return RetrievalResult(
            found=False, reject_reason="no_doc_vectors", diagnostics=diagnostics,
        )

    # 聚合：同 doc_id 取最高分
    best_score: dict[int, float] = {}
    best_text: dict[int, str] = {}
    for vec, score in doc_hits:
        if score > best_score.get(vec.doc_id, -1.0):
            best_score[vec.doc_id] = score
            best_text[vec.doc_id] = vec.text

    # 词法 rerank（方案 7.2 "重排"）
    doc_overlap = {
        did: _lexical_overlap(query, best_text[did]) for did in best_score
    }
    doc_candidates = sorted(
        best_score.keys(),
        key=lambda did: (doc_overlap[did], best_score[did]),
        reverse=True,
    )
    diagnostics["doc_candidates"] = [
        {
            "doc_id": did,
            "score": best_score[did],
            "lexical_overlap": doc_overlap[did],
        }
        for did in doc_candidates[:5]
    ]
    selected_doc_id = doc_candidates[0]
    selected_doc_score = best_score[selected_doc_id]
    selected_doc_overlap = doc_overlap[selected_doc_id]

    # 文档置信度兜底：分数和词法重叠都低，多半是用户没给线索，拒答。
    # 仅当存在多个候选时才检查；只有 1 个候选时没有歧义，必须选它。
    if (
        len(doc_candidates) > 1
        and selected_doc_score < min_doc_score
        and selected_doc_overlap < min_doc_overlap
    ):
        return RetrievalResult(
            found=False,
            doc_method="doc_vectors",
            reject_reason="low_doc_confidence",
            diagnostics=diagnostics,
        )

    # Step 2: 锚点解析（方案 7.3）
    anchor = parse_anchor(query)
    diagnostics["anchor_section_id"] = anchor

    # Step 3: 存在性校验（方案 7.4）
    if anchor != INSUFFICIENT:
        normalized = normalize_section_id(anchor)
        if normalized and re.fullmatch(r"\d+(?:\.\d+)*", normalized):
            if doc_store.section_exists(selected_doc_id, normalized):
                result = doc_store.get_section(selected_doc_id, normalized)
                return RetrievalResult(
                    found=True,
                    doc_id=selected_doc_id,
                    section_id=normalized,
                    title_text=result[0],
                    body_text=result[1],
                    doc_method="doc_vectors",
                    section_method="anchor_exact",
                    diagnostics=diagnostics,
                )

    # Step 4: section_vectors fallback（方案 7.5）
    sec_hits = vector_store.search_sections(query_vec, selected_doc_id, section_top_k)
    if not sec_hits:
        return RetrievalResult(
            found=False, doc_id=selected_doc_id, doc_method="doc_vectors",
            section_method="fallback_empty",
            reject_reason="no_section_vectors",
            diagnostics=diagnostics,
        )

    # 聚合 + 词法 rerank
    best_sec_score: dict[str, float] = {}
    best_sec_text: dict[str, str] = {}
    for vec, score in sec_hits:
        if score > best_sec_score.get(vec.section_id, -1.0):
            best_sec_score[vec.section_id] = score
            best_sec_text[vec.section_id] = vec.text

    sec_overlap = {
        sid: _lexical_overlap(query, best_sec_text[sid]) for sid in best_sec_score
    }
    sec_candidates = sorted(
        best_sec_score.keys(),
        key=lambda sid: (sec_overlap[sid], best_sec_score[sid]),
        reverse=True,
    )
    diagnostics["section_candidates"] = [
        {
            "section_id": sid,
            "score": best_sec_score[sid],
            "lexical_overlap": sec_overlap[sid],
        }
        for sid in sec_candidates[:5]
    ]

    selected_section_id = sec_candidates[0]
    selected_section_score = best_sec_score[selected_section_id]
    selected_section_overlap = sec_overlap[selected_section_id]

    # 章节置信度兜底：fallback 路径要求至少有一个明显信号
    if (
        selected_section_score < min_section_score
        and selected_section_overlap < min_section_overlap
    ):
        return RetrievalResult(
            found=False,
            doc_id=selected_doc_id,
            doc_method="doc_vectors",
            section_method="fallback_vectors",
            reject_reason="low_section_confidence",
            diagnostics=diagnostics,
        )

    # Step 5: 取正文（方案 7.6）
    result = doc_store.get_section(selected_doc_id, selected_section_id)
    return RetrievalResult(
        found=True,
        doc_id=selected_doc_id,
        section_id=selected_section_id,
        title_text=result[0],
        body_text=result[1],
        doc_method="doc_vectors",
        section_method="fallback_vectors",
        diagnostics=diagnostics,
    )
