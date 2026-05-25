from hierarchical_search.pipeline.embedding import HashingEmbedder
from hierarchical_search.pipeline.ingest import ingest_markdown
from hierarchical_search.pipeline.retrieve import retrieve
from hierarchical_search.storage.db import DocStore
from hierarchical_search.storage.vectors import VectorStore


def test_anchor_then_fallback(tmp_path):
    db_path = str(tmp_path / "test.db")
    doc_store = DocStore(db_path)
    vector_store = VectorStore()
    embedder = HashingEmbedder(dim=128)

    markdown = """# 1 相关工作
相关工作正文

# 2 方法
方法总览

## 2.1 实验设置
本节介绍实验设置。

## 2.2 训练细节
本节介绍训练细节。
"""
    ingest_markdown(markdown, "demo.md", "demo.md", embedder, doc_store, vector_store)

    # 锚点命中
    r = retrieve("demo 文档 2.1 讲了什么", embedder, doc_store, vector_store)
    assert r.found is True
    assert r.section_id == "2.1"
    assert r.section_method == "anchor_exact"
    assert "实验设置" in r.body_text

    # 向量兜底
    r = retrieve("实验设置那一节讲了什么", embedder, doc_store, vector_store)
    assert r.found is True
    assert r.section_id == "2.1"
    assert r.section_method == "fallback_vectors"



def _ingest_two_docs(tmp_path):
    db_path = str(tmp_path / "test.db")
    doc_store = DocStore(db_path)
    vector_store = VectorStore()
    embedder = HashingEmbedder(dim=128)

    md_a = """# 1 介绍
A 文档介绍。

# 2 方法
A 文档方法。

## 2.1 实验设置
A 文档的实验设置。
"""
    md_b = """# 1 概述
B 文档概述。

# 2 结论
B 文档结论。
"""
    ingest_markdown(md_a, "alpha.md", "alpha.md", embedder, doc_store, vector_store)
    ingest_markdown(md_b, "beta.md", "beta.md", embedder, doc_store, vector_store)
    return doc_store, vector_store, embedder


def test_low_confidence_rejected_with_multiple_docs(tmp_path):
    doc_store, vector_store, embedder = _ingest_two_docs(tmp_path)
    # query 和两篇文档的标题/文件名都没有任何 token 重叠
    r = retrieve("无法解析的乱码 xyzzy", embedder, doc_store, vector_store)
    assert r.found is False
    assert r.reject_reason == "low_doc_confidence"


def test_anchor_overrides_low_confidence(tmp_path):
    # 即使 doc 选择置信度低，只要 anchor 命中且 section 真实存在，仍应返回
    doc_store, vector_store, embedder = _ingest_two_docs(tmp_path)
    r = retrieve("alpha 2.1", embedder, doc_store, vector_store)
    assert r.found is True
    assert r.section_id == "2.1"
    assert r.section_method == "anchor_exact"


def test_vector_persistence_round_trip(tmp_path):
    db_path = str(tmp_path / "persist.db")
    embedder = HashingEmbedder(dim=128)

    # 第一阶段：ingest + persist
    doc_store_1 = DocStore(db_path)
    vs_1 = VectorStore()
    md = """# 1 相关工作
正文一

# 2 方法
方法总览

## 2.1 实验设置
本节介绍实验设置。
"""
    ingest_markdown(md, "demo.md", "demo.md", embedder, doc_store_1, vs_1)
    vs_1.persist_to(doc_store_1)
    del doc_store_1, vs_1

    # 第二阶段：新 store + 新 vector store + load
    doc_store_2 = DocStore(db_path)
    vs_2 = VectorStore()
    assert vs_2.doc_vectors == []
    vs_2.load_from(doc_store_2)
    assert len(vs_2.doc_vectors) > 0
    assert len(vs_2.section_vectors) > 0

    r = retrieve("demo 2.1 讲了什么", embedder, doc_store_2, vs_2)
    assert r.found is True
    assert r.section_id == "2.1"
    assert r.section_method == "anchor_exact"


def test_load_from_empty_db_is_safe(tmp_path):
    # query 命令在 init-db 之后、ingest 之前调用 load_from 不应崩溃
    db_path = str(tmp_path / "empty.db")
    doc_store = DocStore(db_path)
    vs = VectorStore()
    vs.load_from(doc_store)
    assert vs.doc_vectors == []
    assert vs.section_vectors == []
