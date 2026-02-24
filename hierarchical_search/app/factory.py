from __future__ import annotations

from dataclasses import dataclass

from .config import Settings
from ..ai.embedding import HashingEmbedder, OpenAIEmbedder
from ..ai.llm import OpenAILLMClient, RuleBasedLLMClient
from ..storage.db import Database, DocumentRepository
from ..storage.vector_store.in_memory import InMemoryVectorStore
from ..storage.vector_store.milvus import MilvusVectorStore
from ..storage.vector_store.sqlite import SQLiteVectorStore


@dataclass(slots=True)
class ServiceBundle:
    settings: Settings
    db: Database
    repository: DocumentRepository
    vector_store: object
    embedder: object
    llm_client: object


def build_services(settings: Settings | None = None) -> ServiceBundle:
    settings = settings or Settings.from_env()

    db = Database(settings.database_url)
    repository = DocumentRepository(db)

    if settings.embedding_backend == "openai":
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required when HS_EMBEDDING_BACKEND=openai")
        embedder = OpenAIEmbedder(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            model=settings.openai_embedding_model,
            dim=settings.embedding_dim,
        )
    else:
        embedder = HashingEmbedder(dim=settings.embedding_dim)

    if settings.llm_backend == "openai":
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required when HS_LLM_BACKEND=openai")
        llm_client = OpenAILLMClient(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            model=settings.openai_chat_model,
            prompt_file=settings.prompt_file,
        )
    else:
        llm_client = RuleBasedLLMClient()

    if settings.vector_backend == "milvus":
        vector_store = MilvusVectorStore(
            uri=settings.milvus_uri,
            dim=settings.embedding_dim,
            doc_collection=settings.milvus_doc_collection,
            section_collection=settings.milvus_section_collection,
        )
    elif settings.vector_backend == "memory":
        vector_store = InMemoryVectorStore()
    else:
        vector_store = SQLiteVectorStore(settings.local_vector_path)

    return ServiceBundle(
        settings=settings,
        db=db,
        repository=repository,
        vector_store=vector_store,
        embedder=embedder,
        llm_client=llm_client,
    )
