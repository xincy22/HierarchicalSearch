import os
import uuid

import pytest

from hierarchical_search.ai.embedding import HashingEmbedder
from hierarchical_search.ai.llm import RuleBasedLLMClient
from hierarchical_search.app.config import Settings
from hierarchical_search.services.ingestion import IngestionPipeline
from hierarchical_search.services.retrieval import HierarchicalRetriever
from hierarchical_search.storage.db import Database, DocumentRepository
from hierarchical_search.storage.vector_store.milvus import MilvusVectorStore


def _should_run() -> bool:
    return os.getenv("HS_RUN_MILVUS_TESTS", "").strip() in {"1", "true", "True", "yes", "on"}


@pytest.mark.skipif(not _should_run(), reason="set HS_RUN_MILVUS_TESTS=1 to enable")
def test_milvus_backend_smoke(tmp_path):
    try:
        import pymilvus  # noqa: F401
    except Exception as exc:
        pytest.skip(f"pymilvus not available: {exc}")

    uri = os.getenv("HS_MILVUS_URI", "").strip() or os.getenv("MILVUS_URI", "").strip()
    if not uri:
        pytest.skip("HS_MILVUS_URI is not set")

    unique = uuid.uuid4().hex[:10]
    doc_collection = f"doc_vectors_smoke_{unique}"
    section_collection = f"section_vectors_smoke_{unique}"

    embedder = HashingEmbedder(dim=64)
    llm = RuleBasedLLMClient()

    db_path = tmp_path / "hs.db"
    db = Database(f"sqlite:///{db_path.as_posix()}")
    db.create_tables()
    repo = DocumentRepository(db)

    vector_store = MilvusVectorStore(
        uri=uri,
        dim=embedder.dim,
        doc_collection=doc_collection,
        section_collection=section_collection,
    )
    try:
        pipeline = IngestionPipeline(
            repository=repo,
            vector_store=vector_store,
            embedder=embedder,
            llm_client=llm,
        )
        markdown = """# 1 相关工作
相关工作正文

# 2 方法
方法总览

## 2.1 实验设置
本节介绍实验设置。

## 2.2 训练细节
本节介绍训练细节。
"""
        pipeline.ingest_markdown_text(markdown, filename="demo.md")

        retriever = HierarchicalRetriever(
            settings=Settings(
                database_url=f"sqlite:///{db_path.as_posix()}",
                vector_backend="milvus",
                milvus_uri=uri,
                milvus_doc_collection=doc_collection,
                milvus_section_collection=section_collection,
                embedding_dim=embedder.dim,
            ),
            repository=repo,
            vector_store=vector_store,
            embedder=embedder,
            llm_client=llm,
        )

        anchor_result = retriever.retrieve("demo 文档 2.1 讲了什么")
        assert anchor_result.found is True
        assert anchor_result.section_id == "2.1"
        assert anchor_result.section_method == "anchor_exact"

        fallback_result = retriever.retrieve("实验设置那一节讲了什么")
        assert fallback_result.found is True
        assert fallback_result.section_id == "2.1"
        assert fallback_result.section_method == "fallback_vectors"
    finally:
        # Cleanup Milvus collections to avoid leaking test data.
        for collection in (getattr(vector_store, "doc_collection", None), getattr(vector_store, "section_collection", None)):
            if collection is None:
                continue
            try:
                collection.drop()
            except Exception:
                pass

