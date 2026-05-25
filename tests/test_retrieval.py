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
