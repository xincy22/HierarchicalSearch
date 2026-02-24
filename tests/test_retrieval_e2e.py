from pathlib import Path

from hierarchical_search.ai.embedding import HashingEmbedder
from hierarchical_search.ai.llm import RuleBasedLLMClient
from hierarchical_search.app.config import Settings
from hierarchical_search.services.ingestion import IngestionPipeline
from hierarchical_search.services.retrieval import HierarchicalRetriever
from hierarchical_search.storage.db import Database, DocumentRepository
from hierarchical_search.storage.vector_store.in_memory import InMemoryVectorStore


def test_single_chain_retrieval_anchor_then_fallback(tmp_path: Path):
    db_path = tmp_path / "hs.db"
    db = Database(f"sqlite:///{db_path.as_posix()}")
    db.create_tables()
    repo = DocumentRepository(db)
    vector_store = InMemoryVectorStore()
    embedder = HashingEmbedder(dim=128)
    llm = RuleBasedLLMClient()

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
            vector_backend="memory",
            embedding_dim=128,
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
    assert "实验设置" in (anchor_result.body_text or "")

    fallback_result = retriever.retrieve("实验设置那一节讲了什么")
    assert fallback_result.found is True
    assert fallback_result.section_id == "2.1"
    assert fallback_result.section_method == "fallback_vectors"
