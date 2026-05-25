# HierarchicalSearch

按 [`层级检索.md`](层级检索.md) 实现的单链层级检索：

```
query → doc_id → section_id（锚点优先，向量兜底）→ body_text
```

练手项目。零外部依赖（除了 dev 用 pytest）。

## 适用场景

- 用户问题带章节定位信号（`2.1` / `第2章第3节` / 摘要、引言等）→ 走锚点
- 用户没编号但提到标题关键词（"实验设置那一节"）→ 走章节标题向量兜底

不处理：多轮对话的"上一节"、跨文档事实问答。

## 项目结构

```
hierarchical_search/
├── parsing/          解析层
│   ├── anchor.py     query → section_id
│   └── markdown.py   markdown → sections
├── storage/          存储层
│   ├── db.py         SQLite (documents + sections)
│   └── vectors.py    内存向量
├── pipeline/         流程层
│   ├── embedding.py  hash embedding
│   ├── ingest.py     入库
│   └── retrieve.py   检索
├── cli.py            CLI 入口
└── ...
```

## 安装

```bash
uv venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux
uv pip install -e ".[dev]"
```

## 使用：作为库（推荐）

向量是内存里的，所以"入库 + 查询"必须在同一个进程内完成。

```python
from hierarchical_search.pipeline.embedding import HashingEmbedder
from hierarchical_search.pipeline.ingest import ingest_markdown
from hierarchical_search.pipeline.retrieve import retrieve
from hierarchical_search.storage.db import DocStore
from hierarchical_search.storage.vectors import VectorStore

doc_store = DocStore("hs.db")
vector_store = VectorStore()
embedder = HashingEmbedder(dim=384)

# 入库
markdown = open("examples/sample.md", encoding="utf-8").read()
ingest_markdown(markdown, "sample.md", "sample.md", embedder, doc_store, vector_store)

# 查询
result = retrieve("sample 2.1 讲了什么", embedder, doc_store, vector_store)
print(result.found, result.section_id, result.body_text)
```

返回结果包含：

- `found`、`doc_id`、`section_id`、`title_text`、`body_text`
- `doc_method` / `section_method`：命中方式（`anchor_exact` 或 `fallback_vectors`）
- `diagnostics`：候选列表 + 锚点解析结果，方便排查

## 使用：CLI（仅入库后立刻查询有意义）

```bash
python -m hierarchical_search --db hs.db init-db
python -m hierarchical_search --db hs.db ingest examples/sample.md
python -m hierarchical_search --db hs.db query "sample 2.1 讲了什么"
```

注意：每次 `python -m` 是新进程，`VectorStore` 是空的，所以单独跑 `query` 命令找不到东西。CLI 只适合"入库后立刻查询"的演示场景。要持久化查询能力，把向量也存进 SQLite 即可（这里没做）。

## 测试

```bash
pytest -q
```

## 单链流程

入库（`pipeline/ingest.py`）：

1. `parse_markdown()` 切章节、固化 `section_id`
2. 写 `documents` + `sections`
3. embed `filename + topic + title`（base）+ 多个 alias，写 `doc_vectors`
4. embed 每个章节的层级标题，写 `section_vectors`

检索（`pipeline/retrieve.py`）：

1. `doc_vectors` 召回 → 按 `doc_id` 聚合（取最高分）→ 词法 rerank → 选 top1
2. `parse_anchor(query)` 解析锚点；返回 `INSUFFICIENT` 时表示信息不足
3. 锚点存在 → 直接读 `sections` 返回（`section_method=anchor_exact`）
4. 否则 `section_vectors` 在该 doc 内召回 → 聚合 + rerank → 选 top1（`section_method=fallback_vectors`）
5. 读 `sections` 返回 `body_text`

## 不在范围内的东西

- Milvus、外部 embedding/LLM API：方案里有提，但本实现只用 hash embedding + 内存向量
- 多轮对话上下文
- 跨文档事实问答
- 真实 PDF 解析（输入是 markdown，PDF→markdown 自己接）

## License

MIT
