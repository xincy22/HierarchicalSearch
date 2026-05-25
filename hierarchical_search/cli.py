"""CLI 入口：init-db / ingest / query。"""

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

# 全局单例（进程内共享）
_vector_store = VectorStore()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hierarchical-search")
    parser.add_argument("--db", default="hierarchical_search.db", help="SQLite 数据库路径")
    parser.add_argument("--dim", type=int, default=384, help="embedding 维度")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="创建表")
    p_ingest = sub.add_parser("ingest", help="入库 markdown")
    p_ingest.add_argument("path", help="markdown 文件路径")
    p_query = sub.add_parser("query", help="检索")
    p_query.add_argument("query", help="用户问题")
    p_query.add_argument("--doc-top-k", type=int, default=20)
    p_query.add_argument("--section-top-k", type=int, default=50)

    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    embedder = HashingEmbedder(dim=args.dim)
    doc_store = DocStore(args.db)

    if args.command == "init-db":
        print("OK: tables created.")
        return 0

    if args.command == "ingest":
        doc_id = ingest_file(args.path, embedder, doc_store, _vector_store)
        print(json.dumps({"doc_id": doc_id}, ensure_ascii=False))
        return 0

    if args.command == "query":
        result = retrieve(
            args.query, embedder, doc_store, _vector_store,
            doc_top_k=args.doc_top_k, section_top_k=args.section_top_k,
        )
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
