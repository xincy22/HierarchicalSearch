from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


def _parse_env_value(raw_value: str) -> str:
    value = raw_value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    if " #" in value:
        value = value.split(" #", 1)[0].rstrip()
    return value


def _load_env_file(path: str) -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if key:
            os.environ.setdefault(key, _parse_env_value(raw_value))


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class Settings:
    database_url: str = "sqlite:///hierarchical_search.db"
    vector_backend: str = "local"
    embedding_backend: str = "hash"
    llm_backend: str = "rule"
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    openai_embedding_model: str = "text-embedding-3-small"
    openai_chat_model: str = "gpt-4o-mini"
    prompt_file: str | None = None
    milvus_uri: str = "http://localhost:19530"
    milvus_doc_collection: str = "doc_vectors"
    milvus_section_collection: str = "section_vectors"
    local_vector_path: str = "hierarchical_vectors.db"
    embedding_dim: int = 384
    doc_top_k: int = 20
    section_top_k: int = 50
    llm_rerank_enabled: bool = True

    @classmethod
    def from_env(cls) -> "Settings":
        _load_env_file(os.getenv("HS_ENV_FILE", ".env"))
        defaults = cls()
        return cls(
            database_url=os.getenv("HS_DATABASE_URL", defaults.database_url),
            vector_backend=os.getenv("HS_VECTOR_BACKEND", defaults.vector_backend),
            embedding_backend=os.getenv("HS_EMBEDDING_BACKEND", defaults.embedding_backend),
            llm_backend=os.getenv("HS_LLM_BACKEND", defaults.llm_backend),
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            openai_base_url=os.getenv("HS_OPENAI_BASE_URL", os.getenv("OPENAI_BASE_URL")),
            openai_embedding_model=os.getenv(
                "HS_OPENAI_EMBEDDING_MODEL", defaults.openai_embedding_model
            ),
            openai_chat_model=os.getenv("HS_OPENAI_CHAT_MODEL", defaults.openai_chat_model),
            prompt_file=os.getenv("HS_PROMPT_FILE"),
            milvus_uri=os.getenv("HS_MILVUS_URI", defaults.milvus_uri),
            milvus_doc_collection=os.getenv(
                "HS_MILVUS_DOC_COLLECTION", defaults.milvus_doc_collection
            ),
            milvus_section_collection=os.getenv(
                "HS_MILVUS_SECTION_COLLECTION", defaults.milvus_section_collection
            ),
            local_vector_path=os.getenv("HS_LOCAL_VECTOR_PATH", defaults.local_vector_path),
            embedding_dim=int(os.getenv("HS_EMBEDDING_DIM", str(defaults.embedding_dim))),
            doc_top_k=int(os.getenv("HS_DOC_TOP_K", str(defaults.doc_top_k))),
            section_top_k=int(os.getenv("HS_SECTION_TOP_K", str(defaults.section_top_k))),
            llm_rerank_enabled=_env_bool("HS_LLM_RERANK_ENABLED", defaults.llm_rerank_enabled),
        )
