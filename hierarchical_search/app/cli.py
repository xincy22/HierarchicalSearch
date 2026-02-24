from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import sys

from .config import Settings
from .factory import build_services
from ..services.ingestion import IngestionPipeline
from ..services.retrieval import HierarchicalRetriever


def _build_settings_from_args(args: argparse.Namespace) -> Settings:
    s = Settings.from_env()
    if getattr(args, "database_url", None):
        s.database_url = args.database_url
    if getattr(args, "vector_backend", None):
        s.vector_backend = args.vector_backend
    if getattr(args, "local_vector_path", None):
        s.local_vector_path = args.local_vector_path
    if getattr(args, "embedding_backend", None):
        s.embedding_backend = args.embedding_backend
    if getattr(args, "llm_backend", None):
        s.llm_backend = args.llm_backend
    if getattr(args, "prompt_file", None):
        s.prompt_file = args.prompt_file
    return s


def _add_common_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--vector-backend", choices=["local", "memory", "milvus"], default=None)
    parser.add_argument("--local-vector-path", default=None)
    parser.add_argument("--embedding-backend", choices=["hash", "openai"], default=None)
    parser.add_argument("--llm-backend", choices=["rule", "openai"], default=None)
    parser.add_argument("--prompt-file", default=None)


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]

    parser = argparse.ArgumentParser(prog="hierarchical-search")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_db_parser = subparsers.add_parser("init-db", help="create MySQL/SQLite tables")
    _add_common_flags(init_db_parser)

    ingest_parser = subparsers.add_parser("ingest", help="ingest one markdown file")
    ingest_parser.add_argument("path", help="path to markdown file")
    _add_common_flags(ingest_parser)

    query_parser = subparsers.add_parser("query", help="run one retrieval query")
    query_parser.add_argument("query", help="user question")
    _add_common_flags(query_parser)

    args = parser.parse_args(argv)
    settings = _build_settings_from_args(args)
    services = build_services(settings)

    if args.command == "init-db":
        services.db.create_tables()
        print("OK: tables created.")
        return 0

    if args.command == "ingest":
        services.db.create_tables()
        pipeline = IngestionPipeline(
            repository=services.repository,
            vector_store=services.vector_store,
            embedder=services.embedder,
            llm_client=services.llm_client,
        )
        result = pipeline.ingest_markdown_file(args.path)
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        return 0

    if args.command == "query":
        retriever = HierarchicalRetriever(
            settings=services.settings,
            repository=services.repository,
            vector_store=services.vector_store,
            embedder=services.embedder,
            llm_client=services.llm_client,
        )
        result = retriever.retrieve(args.query)
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        return 0

    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
