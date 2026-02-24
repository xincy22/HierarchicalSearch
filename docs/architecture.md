# Architecture

本项目实现一个“两级索引 + 单链检索”的层级检索模块：

`doc_id -> section_id(anchor优先, vector兜底) -> body_text`

目标是让用户带编号的问题（例如 `2.1` / `第2章第3节`）能稳定命中，而标题类问题（“实验设置那一节”）在锚点信息不足时再回退向量检索。

## 核心数据

### SQL（documents/sections）

- `documents`：一篇文档一行，`doc_key` 作为唯一标识（避免同名文件覆盖），稳定 `doc_id`；`filename` 用于展示
- `sections`：章节内容表，主键 `(doc_id, section_id)`，直接返回 `body_text`

关键点：

- `section_id` 只使用数字路径：`^\d+(\.\d+)*$`（例如 `2` / `2.1` / `3.2.1`）
- 解析阶段会把 markdown 的标题行固化为 `section_id`，并保留 `heading_raw`、`heading_prefix_raw` 便于诊断

### Vector（doc_vectors/section_vectors）

用于两级向量召回：

- `doc_vectors`：输入 query embedding，召回候选 doc_id
- `section_vectors`：在 doc 内召回候选 section_id（仅兜底路径）

设计原则：

- `doc_vectors` 的文本可以包含 filename/topic/title/alias（便于文档定位）
- `section_vectors` 的文本只包含层级标题（避免 doc 信息干扰章节区分）

## 入库流程（Ingestion）

入口：`python -m hierarchical_search ingest <markdown>`

代码：`hierarchical_search/services/ingestion.py`

步骤（概念上）：

1. markdown 解析出 heading 列表与正文块（并固化 `section_id`）
2. 写 `documents` 生成 `doc_id`
3. 生成 doc 的多个“检索变体”（base + aliases），写入 `doc_vectors`
4. 写入 `sections`（最终正文落点）
5. 生成每个 section 的向量文本，写入 `section_vectors`

## 在线检索单链（Retrieval）

入口：`python -m hierarchical_search query "<question>"`

代码：`hierarchical_search/services/retrieval.py`

单链逻辑（伪代码）：

1. `query_vec = embed(query)`
2. doc 召回：`doc_hits = search(doc_vectors, query_vec)`
3. doc 候选聚合 + 重排（本地词法优先，必要时才 LLM 重排）
4. 尝试从 query 解析锚点 `section_id`（能确定就直接校验存在性）
5. 若锚点存在：读取 `sections` 返回
6. 否则：在 doc 内做 section 向量兜底，选最优 section 并返回正文

## 锚点解析（Anchor）

代码：`hierarchical_search/parsers/anchor.py`

锚点策略是“保守不硬猜”：

- 能确定唯一编号：直接输出数字路径（`2.1`, `3.2.1`, `第2章第3节`）
- 信息不足/歧义：输出 `INSUFFICIENT`，进入向量兜底

## 诊断（Diagnostics）

返回结构中包含：

- `doc_method` / `section_method`
- `doc_candidates` / `section_candidates`（top-N）
- `anchor_section_id`（锚点解析结果）

建议做线上观测时把 `diagnostics` 存档一段时间，便于定位问题归因：

- doc 定位错？（doc_vectors + rerank）
- 锚点解析错？（anchor parser / LLM）
- section 向量兜底错？（embedding、topK、标题切分、正文边界）
