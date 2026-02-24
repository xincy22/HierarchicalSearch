from pathlib import Path

from hierarchical_search.ai.embedding import HashingEmbedder
from hierarchical_search.ai.llm import RuleBasedLLMClient
from hierarchical_search.services.ingestion import IngestionPipeline
from hierarchical_search.storage.db import Database, DocumentRepository
from hierarchical_search.storage.vector_store.in_memory import InMemoryVectorStore


def test_ingest_markdown_file_uses_relative_doc_key(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a").mkdir()
    md_path = tmp_path / "a" / "demo.md"
    md_path.write_text("# 1 A\nbody\n", encoding="utf-8")

    db_path = tmp_path / "hs.db"
    db = Database(f"sqlite:///{db_path.as_posix()}")
    db.create_tables()
    repo = DocumentRepository(db)

    pipeline = IngestionPipeline(
        repository=repo,
        vector_store=InMemoryVectorStore(),
        embedder=HashingEmbedder(dim=32),
        llm_client=RuleBasedLLMClient(),
    )
    result = pipeline.ingest_markdown_file("a/demo.md")
    doc = repo.get_document(result.doc_id)
    assert doc is not None
    assert doc.doc_key == "a/demo.md"
    assert doc.filename == "demo.md"


def test_same_filename_different_paths_do_not_collide(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "a" / "demo.md").write_text("# 1 A\nA\n", encoding="utf-8")
    (tmp_path / "b" / "demo.md").write_text("# 1 B\nB\n", encoding="utf-8")

    db_path = tmp_path / "hs.db"
    db = Database(f"sqlite:///{db_path.as_posix()}")
    db.create_tables()
    repo = DocumentRepository(db)

    pipeline = IngestionPipeline(
        repository=repo,
        vector_store=InMemoryVectorStore(),
        embedder=HashingEmbedder(dim=32),
        llm_client=RuleBasedLLMClient(),
    )
    a = pipeline.ingest_markdown_file("a/demo.md")
    b = pipeline.ingest_markdown_file("b/demo.md")

    assert a.doc_id != b.doc_id
    doc_a = repo.get_document(a.doc_id)
    doc_b = repo.get_document(b.doc_id)
    assert doc_a is not None and doc_b is not None
    assert doc_a.doc_key == "a/demo.md"
    assert doc_b.doc_key == "b/demo.md"

