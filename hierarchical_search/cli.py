"""CLI 入口：init-db / ingest / query / demo。

向量在 ingest 时会持久化到 SQLite，query 时自动加载，
所以这两个命令可以独立跨进程使用。demo 用于快速演示，全程同进程。
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import sys

from .pipeline.embedding import HashingEmbedder
from .pipeline.ingest import ingest_file
from .pipeline.retrieve import retrieve
from .storage.db import DocStore
from .storage.vectors import VectorStore


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hierarchical-search")
    parser.add_argument(
        "--db", default="hierarchical_search.db", help="SQLite 数据库路径"
    )
    parser.add_argument("--dim", type=int, default=384, help="embedding 维度")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="创建表")

    p_ingest = sub.add_parser("ingest", help="入库 markdown（自动持久化向量）")
    p_ingest.add_argument("path", help="markdown 文件路径")

    p_query = sub.add_parser("query", help="检索（自动从 SQLite 加载向量）")
    p_query.add_argument("query", help="用户问题")
    p_query.add_argument("--doc-top-k", type=int, default=20)
    p_query.add_argument("--section-top-k", type=int, default=50)

    p_demo = sub.add_parser(
        "demo", help="同进程内 ingest + query，便于演示与调试"
    )
    p_demo.add_argument("path", help="markdown 文件路径")
    p_demo.add_argument("query", help="用户问题")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    embedder = HashingEmbedder(dim=args.dim)
    doc_store = DocStore(args.db)
    vector_store = VectorStore()

    if args.command == "init-db":
        print("OK: tables created.")
        return 0

    if args.command == "ingest":
        # 入库前先把已有向量加载进内存，再写入新文档，最后整体持久化
        vector_store.load_from(doc_store)
        doc_id = ingest_file(args.path, embedder, doc_store, vector_store)
        vector_store.persist_to(doc_store)
        print(json.dumps({"doc_id": doc_id}, ensure_ascii=False))
        return 0

    if args.command == "query":
        vector_store.load_from(doc_store)
        result = retrieve(
            args.query, embedder, doc_store, vector_store,
            doc_top_k=args.doc_top_k, section_top_k=args.section_top_k,
        )
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        return 0

    if args.command == "demo":
        ingest_file(args.path, embedder, doc_store, vector_store)
        result = retrieve(args.query, embedder, doc_store, vector_store)
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
