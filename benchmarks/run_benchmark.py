from __future__ import annotations

import argparse
from dataclasses import asdict
from dataclasses import dataclass
import json
from pathlib import Path
from statistics import mean
import tempfile
import time

from hierarchical_search.ai.llm import RuleBasedLLMClient
from hierarchical_search.app.config import Settings
from hierarchical_search.app.factory import build_services
from hierarchical_search.services.ingestion import IngestionPipeline
from hierarchical_search.services.retrieval import HierarchicalRetriever


@dataclass(slots=True)
class DocumentSpec:
    filename: str
    markdown: str


@dataclass(slots=True)
class QueryCase:
    query: str
    expected_filename: str
    expected_section_id: str
    scenario: str


def _corpus() -> tuple[list[DocumentSpec], list[QueryCase]]:
    docs = [
        DocumentSpec(
            filename="机器学习导论.md",
            markdown="""
# 1 基础概念
介绍基本术语与任务类型。

# 2 监督学习
监督学习方法总览。

## 2.1 线性模型
讲解线性回归与逻辑回归的核心思想。

## 2.2 决策树
讲解信息增益与树结构。

# 3 实验设置
实验流程概览。

## 3.1 数据集
介绍训练和测试数据集。

## 3.2 评估指标
介绍准确率、召回率和F1。
""".strip(),
        ),
        DocumentSpec(
            filename="检索系统实践.md",
            markdown="""
# 1 背景
介绍检索系统问题背景。

# 2 系统架构
系统模块拆分说明。

## 2.1 倒排索引
讲解词项字典、posting list 和布尔检索。

## 2.2 向量检索
讲解向量召回与 ANN。

# 3 评测
评测流程说明。

## 3.1 数据集
介绍评测数据集构建。

## 3.2 召回率
介绍 Recall@K 的定义和使用。
""".strip(),
        ),
        DocumentSpec(
            filename="数据库系统原理.md",
            markdown="""
# 1 存储引擎
介绍行存和列存。

# 2 事务
事务的性质与实现。

## 2.1 ACID
介绍原子性、一致性、隔离性、持久性。

## 2.2 隔离级别
介绍读未提交、读已提交、可重复读、串行化。

# 3 索引
索引方法总览。

## 3.1 B+树
介绍范围查询优势。

## 3.2 哈希索引
介绍点查优势。
""".strip(),
        ),
        DocumentSpec(
            filename="操作系统设计.md",
            markdown="""
# 1 进程线程
介绍进程和线程模型。

# 2 调度
介绍CPU调度目标。

## 2.1 时间片
介绍轮转调度中的时间片策略。

## 2.2 优先级
介绍优先级调度与饥饿问题。

# 3 内存管理
介绍地址空间管理。

## 3.1 分页
介绍页表机制。

## 3.2 虚拟内存
介绍按需分页和页面置换。
""".strip(),
        ),
        DocumentSpec(
            filename="分布式系统导论.md",
            markdown="""
# 1 共识
介绍分布式共识问题。

# 2 容错
介绍失效检测与故障恢复。

## 2.1 心跳
介绍心跳机制和超时策略。

## 2.2 副本复制
介绍主从复制和多副本。

# 3 一致性
介绍一致性模型。

## 3.1 线性一致性
介绍强一致语义。

## 3.2 最终一致性
介绍异步复制下的一致性收敛。
""".strip(),
        ),
    ]

    queries = [
        QueryCase("机器学习导论 2.1 讲了什么", "机器学习导论.md", "2.1", "anchor"),
        QueryCase("机器学习导论 2.2 的内容", "机器学习导论.md", "2.2", "anchor"),
        QueryCase("机器学习导论 第3章讲了什么", "机器学习导论.md", "3", "anchor"),
        QueryCase("机器学习导论 决策树这一节讲了什么", "机器学习导论.md", "2.2", "title"),
        QueryCase("机器学习导论 评估指标部分讲了什么", "机器学习导论.md", "3.2", "title"),
        QueryCase("机器学习导论 线性模型主要内容", "机器学习导论.md", "2.1", "title"),
        QueryCase("检索系统实践 2.1 讲了什么", "检索系统实践.md", "2.1", "anchor"),
        QueryCase("检索系统实践 第2章讲了什么", "检索系统实践.md", "2", "anchor"),
        QueryCase("检索系统实践 第3章第2节", "检索系统实践.md", "3.2", "anchor"),
        QueryCase("检索系统实践 倒排索引这一节在说什么", "检索系统实践.md", "2.1", "title"),
        QueryCase("检索系统实践 向量检索这一节讲了什么", "检索系统实践.md", "2.2", "title"),
        QueryCase("检索系统实践 召回率怎么定义", "检索系统实践.md", "3.2", "title"),
        QueryCase("数据库系统原理 2.1 讲了什么", "数据库系统原理.md", "2.1", "anchor"),
        QueryCase("数据库系统原理 第3章", "数据库系统原理.md", "3", "anchor"),
        QueryCase("数据库系统原理 第2章第2节讲了什么", "数据库系统原理.md", "2.2", "anchor"),
        QueryCase("数据库系统原理 ACID 这一节内容", "数据库系统原理.md", "2.1", "title"),
        QueryCase("数据库系统原理 隔离级别部分讲了什么", "数据库系统原理.md", "2.2", "title"),
        QueryCase("数据库系统原理 B+树索引讲了什么", "数据库系统原理.md", "3.1", "title"),
        QueryCase("操作系统设计 2.1 讲了什么", "操作系统设计.md", "2.1", "anchor"),
        QueryCase("操作系统设计 第3章讲了什么", "操作系统设计.md", "3", "anchor"),
        QueryCase("操作系统设计 第2章第2节讲了什么", "操作系统设计.md", "2.2", "anchor"),
        QueryCase("操作系统设计 时间片调度是什么", "操作系统设计.md", "2.1", "title"),
        QueryCase("操作系统设计 优先级调度讲了什么", "操作系统设计.md", "2.2", "title"),
        QueryCase("操作系统设计 虚拟内存这一节", "操作系统设计.md", "3.2", "title"),
        QueryCase("分布式系统导论 2.1 讲了什么", "分布式系统导论.md", "2.1", "anchor"),
        QueryCase("分布式系统导论 第3章", "分布式系统导论.md", "3", "anchor"),
        QueryCase("分布式系统导论 第2章第2节", "分布式系统导论.md", "2.2", "anchor"),
        QueryCase("分布式系统导论 心跳机制讲了什么", "分布式系统导论.md", "2.1", "title"),
        QueryCase("分布式系统导论 副本复制怎么做", "分布式系统导论.md", "2.2", "title"),
        QueryCase("分布式系统导论 线性一致性部分", "分布式系统导论.md", "3.1", "title"),
    ]
    return docs, queries


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    rank = (len(values) - 1) * (p / 100.0)
    lower = int(rank)
    upper = min(lower + 1, len(values) - 1)
    if lower == upper:
        return values[lower]
    weight = rank - lower
    return values[lower] * (1.0 - weight) + values[upper] * weight


def run_benchmark(args: argparse.Namespace) -> dict[str, object]:
    docs, all_cases = _corpus()
    if args.limit_cases > 0:
        cases = all_cases[: args.limit_cases]
    else:
        cases = all_cases

    with tempfile.TemporaryDirectory(prefix="hs_bench_") as tmpdir:
        tmp = Path(tmpdir)
        db_path = tmp / "bench.db"
        vec_path = tmp / "vectors.db"

        settings = Settings.from_env()
        settings.database_url = f"sqlite:///{db_path.as_posix()}"
        settings.vector_backend = "local"
        settings.local_vector_path = vec_path.as_posix()
        settings.embedding_backend = args.embedding_backend
        settings.llm_backend = args.llm_backend

        services = build_services(settings)
        try:
            services.db.create_tables()

            pipeline = IngestionPipeline(
                repository=services.repository,
                vector_store=services.vector_store,
                embedder=services.embedder,
                llm_client=(
                    RuleBasedLLMClient()
                    if args.ingest_llm_backend == "rule"
                    else services.llm_client
                ),
            )
            retriever = HierarchicalRetriever(
                settings=services.settings,
                repository=services.repository,
                vector_store=services.vector_store,
                embedder=services.embedder,
                llm_client=services.llm_client,
            )

            ingest_start = time.perf_counter()
            doc_id_map: dict[str, int] = {}
            for doc in docs:
                result = pipeline.ingest_markdown_text(doc.markdown, doc.filename)
                doc_id_map[doc.filename] = result.doc_id
            ingest_seconds = time.perf_counter() - ingest_start

            warmup_n = max(0, min(args.warmup, len(cases)))
            for case in cases[:warmup_n]:
                retriever.retrieve(case.query)

            latencies_ms: list[float] = []
            exact_match = 0
            doc_match = 0
            found_count = 0
            method_counts: dict[str, int] = {}
            scenario_totals: dict[str, int] = {}
            scenario_hits: dict[str, int] = {}
            failures: list[dict[str, object]] = []

            query_start = time.perf_counter()
            for _ in range(max(1, args.runs)):
                for case in cases:
                    t0 = time.perf_counter()
                    result = retriever.retrieve(case.query)
                    latency_ms = (time.perf_counter() - t0) * 1000.0
                    latencies_ms.append(latency_ms)

                    expected_doc_id = doc_id_map[case.expected_filename]
                    is_doc_ok = result.doc_id == expected_doc_id
                    is_section_ok = result.section_id == case.expected_section_id
                    is_exact = result.found and is_doc_ok and is_section_ok

                    scenario_totals[case.scenario] = scenario_totals.get(case.scenario, 0) + 1
                    if is_exact:
                        scenario_hits[case.scenario] = scenario_hits.get(case.scenario, 0) + 1
                    else:
                        failures.append(
                            {
                                "query": case.query,
                                "expected_doc_id": expected_doc_id,
                                "expected_section_id": case.expected_section_id,
                                "actual_doc_id": result.doc_id,
                                "actual_section_id": result.section_id,
                                "found": result.found,
                                "section_method": result.section_method,
                            }
                        )

                    if result.found:
                        found_count += 1
                    if is_doc_ok:
                        doc_match += 1
                    if is_exact:
                        exact_match += 1
                    method = result.section_method or "unknown"
                    method_counts[method] = method_counts.get(method, 0) + 1

            query_seconds = time.perf_counter() - query_start
            latencies_ms.sort()

            total_queries = len(latencies_ms)
            accuracy_by_scenario = {
                name: (scenario_hits.get(name, 0) / total if total else 0.0)
                for name, total in scenario_totals.items()
            }

            report: dict[str, object] = {
                "config": {
                    "llm_backend": args.llm_backend,
                    "embedding_backend": args.embedding_backend,
                    "runs": args.runs,
                    "warmup": warmup_n,
                    "corpus_docs": len(docs),
                    "query_cases": len(cases),
                    "total_queries": total_queries,
                },
                "ingestion": {
                    "seconds": round(ingest_seconds, 4),
                    "docs_per_second": round(len(docs) / ingest_seconds, 4)
                    if ingest_seconds > 0
                    else 0.0,
                },
                "quality": {
                    "found_rate": round(found_count / total_queries, 4)
                    if total_queries
                    else 0.0,
                    "doc_accuracy": round(doc_match / total_queries, 4)
                    if total_queries
                    else 0.0,
                    "exact_accuracy": round(exact_match / total_queries, 4)
                    if total_queries
                    else 0.0,
                    "accuracy_by_scenario": accuracy_by_scenario,
                },
                "latency_ms": {
                    "mean": round(mean(latencies_ms), 3) if latencies_ms else 0.0,
                    "p50": round(_percentile(latencies_ms, 50), 3),
                    "p95": round(_percentile(latencies_ms, 95), 3),
                    "p99": round(_percentile(latencies_ms, 99), 3),
                    "max": round(latencies_ms[-1], 3) if latencies_ms else 0.0,
                },
                "throughput": {
                    "qps": round(total_queries / query_seconds, 3)
                    if query_seconds > 0
                    else 0.0,
                    "query_seconds": round(query_seconds, 4),
                },
                "section_method_counts": method_counts,
                "sample_failures": failures[: args.max_failures],
            }

            llm_stats = getattr(services.llm_client, "stats", None)
            if isinstance(llm_stats, dict):
                report["llm_stats"] = dict(llm_stats)
            return report
        finally:
            conn = getattr(services.vector_store, "conn", None)
            if conn is not None:
                conn.close()
            engine = getattr(services.db, "engine", None)
            if engine is not None:
                engine.dispose()


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run hierarchical retrieval benchmark.")
    parser.add_argument("--runs", type=int, default=2, help="repeat query set N times")
    parser.add_argument(
        "--warmup", type=int, default=6, help="warmup query count before measuring"
    )
    parser.add_argument(
        "--llm-backend", choices=["rule", "openai"], default="rule", help="LLM backend"
    )
    parser.add_argument(
        "--embedding-backend",
        choices=["hash", "openai"],
        default="hash",
        help="Embedding backend",
    )
    parser.add_argument(
        "--max-failures", type=int, default=12, help="max failures to include in report"
    )
    parser.add_argument(
        "--output-json", type=str, default="", help="optional path to write report JSON"
    )
    parser.add_argument(
        "--limit-cases",
        type=int,
        default=0,
        help="only benchmark first N query cases (0 means all)",
    )
    parser.add_argument(
        "--ingest-llm-backend",
        choices=["same", "rule"],
        default="same",
        help="LLM backend used during ingestion stage",
    )
    return parser


def main() -> int:
    parser = _build_arg_parser()
    args = parser.parse_args()

    report = run_benchmark(args)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.output_json:
        Path(args.output_json).write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
