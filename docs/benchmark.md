# Benchmark

仓库内置一个合成语料 benchmark：`benchmarks/run_benchmark.py`

它的定位是：

- 快速回归：验证“单链流程”是否被改坏
- 快速对比：改动前后准确率/时延变化

不代表真实 PDF 解析噪声（OCR/标题错分/编号缺失/表格干扰等）。

## 1. 运行

离线（rule/hash）：

```bash
python benchmarks/run_benchmark.py --runs 1 --warmup 4 --llm-backend rule --embedding-backend hash
```

输出 JSON 文件：

```bash
python benchmarks/run_benchmark.py --output-json benchmarks/report.json
```

## 2. 指标含义

输出里包含：

- `quality.found_rate`：是否能找到结果
- `quality.doc_accuracy`：doc_id 是否正确
- `quality.exact_accuracy`：doc_id + section_id 是否都正确
- `latency_ms.p50/p95/p99`：单次 `retrieve()` 的延迟分位数
- `throughput.qps`：在本机上的吞吐（注意：受缓存/限流/网络影响很大）

## 3. 关键参数

- `--runs`：重复跑整个 query set 的次数（用于平滑波动）
- `--warmup`：热身 query 数（避免首次加载的偏差）
- `--limit-cases`：只跑前 N 条 case（快速调试）
- `--ingest-llm-backend`：
  - `same`：入库与查询都用同一 LLM 后端
  - `rule`：入库阶段强制用 rule（避免入库时大量远程调用）

## 4. 做真实 PDF 评测（建议）

如果你暂时没有 MinerU 云 API，也不想本地部署 MinerU，可以先用“替代解析器”把 PDF 转成 markdown，再走同样的 `ingest -> query` 链路。

推荐路线：

1. 选择一个 PDF-to-text/markdown 工具（例如 PyMuPDF/pdfplumber）
2. 选 10-30 份真实 PDF 做一个小金标集
3. 每份 5-10 条问题，标注期望 `(doc_id, section_id)`（或至少标注 section_id）
4. 输出三组指标：
   - 理想 markdown（对照组）
   - 真实 PDF 转换结果
   - 真实 PDF + 噪声注入（标题错字/编号缺失等）

这样能回答“这个层级检索在真实世界到底靠谱吗”。

