# HierarchicalSearch

按 [`层级检索.md`](层级检索.md) 实现的单链层级检索：

```
query → doc_id → section_id（锚点优先，向量兜底）→ body_text
```

练手项目。零运行时依赖（仅标准库），dev 用 pytest。

---

## 目录

- [设计目标](#设计目标)
- [适用场景与边界](#适用场景与边界)
- [项目结构](#项目结构)
- [安装](#安装)
- [快速开始（库）](#快速开始库)
- [快速开始（CLI）](#快速开始cli)
- [API 速查](#api-速查)
- [数据模型](#数据模型)
- [入库流程详解](#入库流程详解)
- [检索流程详解](#检索流程详解)
- [锚点解析规则](#锚点解析规则)
- [Markdown 解析规则](#markdown-解析规则)
- [诊断与排查](#诊断与排查)
- [测试](#测试)
- [已知限制](#已知限制)

---

## 设计目标

向量检索对数字 token 表达不可靠：用户问 "XXX 论文 2.1 讲了什么"，把 `filename + topic + l1 + l2` 拼起来 embed，`2.1` 几乎不可能出现在 topK。

所以这个方案**先用规则把锚点抽出来**，向量只负责两件事：

1. 定位 `doc_id`（用户可能用简称、别名、英文名）
2. 当 query 里没有可解析的锚点时，在已选 doc 内按章节标题做兜底

整条链路是单向的，没有多分支。

## 适用场景与边界

**处理：**

- 锚点型：`2.1`、`第2章第3节`、`摘要`、`引言` 等
- 标题指向型：`实验设置那一节`、`相关工作部分`（无编号但有关键词）

**不处理：**

- 多轮上下文（`这一节`、`上一节` 不在边界内，无对话历史）
- 跨文档事实问答（这是通用 RAG 的活）
- 用户没有任何线索（没编号、没关键词）

## 项目结构

三层概念，每层职责单一：

```
hierarchical_search/
├── parsing/                解析层：原始文本 → 结构化
│   ├── anchor.py           query → section_id 或 INSUFFICIENT
│   └── markdown.py         markdown → Section 列表（固化 section_id）
├── storage/                存储层
│   ├── db.py               SQLite (documents + sections)
│   └── vectors.py          内存向量 (doc_vectors + section_vectors)
├── pipeline/               流程层
│   ├── embedding.py        hash embedding（共用）
│   ├── ingest.py           入库流水线
│   └── retrieve.py         单链检索
├── cli.py                  CLI 入口
├── __init__.py
└── __main__.py
```

依赖方向：`pipeline → parsing + storage`，`storage` 和 `parsing` 互不依赖。

## 安装

需要 Python 3.10+，推荐用 `uv` 管理虚拟环境：

```bash
uv venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux
uv pip install -e ".[dev]"
```

## 快速开始（库）

向量是内存里的，所以**入库 + 查询必须在同一个进程内**。这是推荐用法。

```python
from hierarchical_search.pipeline.embedding import HashingEmbedder
from hierarchical_search.pipeline.ingest import ingest_markdown
from hierarchical_search.pipeline.retrieve import retrieve
from hierarchical_search.storage.db import DocStore
from hierarchical_search.storage.vectors import VectorStore

# 1. 装配三个核心组件
doc_store = DocStore("hs.db")          # SQLite 文件，可重用
vector_store = VectorStore()           # 内存，进程结束即清空
embedder = HashingEmbedder(dim=384)    # 维度可调

# 2. 入库
markdown = open("examples/sample.md", encoding="utf-8").read()
ingest_markdown(
    markdown=markdown,
    filename="sample.md",
    doc_key="sample.md",        # 唯一标识，建议用相对路径
    embedder=embedder,
    doc_store=doc_store,
    vector_store=vector_store,
)

# 3. 查询
result = retrieve("sample 2.1 讲了什么", embedder, doc_store, vector_store)
print(result.found, result.section_id, result.section_method)
print(result.body_text)
```

输出大概长这样：

```
True 2.1 anchor_exact
本节介绍实验设置。
```

## 快速开始（CLI）

CLI 在每次 `python -m` 调用时是新进程，`VectorStore` 会重新初始化为空。所以 CLI **只适合"入库后立刻查询"的演示**：

```bash
python -m hierarchical_search --db hs.db init-db
python -m hierarchical_search --db hs.db ingest examples/sample.md
python -m hierarchical_search --db hs.db query "sample 2.1 讲了什么"
```

注意 `--db` 必须在子命令之前。

要让查询命令独立可用，需要把向量也持久化到 SQLite（这里没做，留给你扩展）。

## API 速查

### `pipeline.ingest`

```python
ingest_markdown(markdown, filename, doc_key, embedder, doc_store, vector_store) -> int
ingest_file(path, embedder, doc_store, vector_store) -> int
```

返回 `doc_id`。

`doc_key` 是你选的唯一标识。同一个 `doc_key` 重复入库会**覆盖**对应文档（更新 documents 行 + 重新写 sections + 重新写 vectors）。

### `pipeline.retrieve`

```python
retrieve(query, embedder, doc_store, vector_store, doc_top_k=20, section_top_k=50)
    -> RetrievalResult
```

`RetrievalResult` 字段：

| 字段 | 说明 |
|------|------|
| `found` | 是否找到结果 |
| `doc_id` | 命中文档 |
| `section_id` | 命中章节，如 `2.1` |
| `title_text` / `body_text` | 章节标题/正文 |
| `doc_method` | 文档命中方式（目前固定 `doc_vectors`） |
| `section_method` | 章节命中方式：`anchor_exact` 或 `fallback_vectors` |
| `diagnostics` | 候选列表 + 锚点解析结果 |

### `parsing.anchor`

```python
parse_anchor(query: str) -> str        # 返回 section_id 或 "INSUFFICIENT"
normalize_section_id(s: str) -> str | None
cn_to_int(s: str) -> int | None        # "二十三" → 23
```

### `parsing.markdown`

```python
parse_markdown(markdown: str) -> list[Section]
```

`Section` 字段：`section_id, level, title_text, body_text, l1_title, l2_title, l3_title`。

### `storage.db`

```python
class DocStore:
    upsert_document(doc_key, filename, file_topic, doc_title) -> int
    replace_sections(doc_id, [(section_id, level, title, body), ...])
    section_exists(doc_id, section_id) -> bool
    get_section(doc_id, section_id) -> tuple[str, str] | None  # (title, body)
```

### `storage.vectors`

```python
class VectorStore:
    add_doc_vectors(doc_id, vectors: list[DocVector])
    add_section_vectors(doc_id, vectors: list[SectionVector])
    search_docs(query_vec, top_k) -> list[tuple[DocVector, float]]
    search_sections(query_vec, doc_id, top_k) -> list[tuple[SectionVector, float]]
```

## 数据模型

### SQLite

```sql
documents (
    doc_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_key     TEXT UNIQUE NOT NULL,    -- 业务侧唯一标识
    filename    TEXT NOT NULL,           -- 展示用文件名
    file_topic  TEXT NOT NULL,           -- 文档主题（取第一个标题）
    doc_title   TEXT                     -- 文档标题（同上或文件名 stem）
);

sections (
    doc_id      INTEGER NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    section_id  TEXT NOT NULL,           -- '1', '2.1', '0.1' 等
    level       INTEGER NOT NULL,        -- 1/2/3
    title_text  TEXT NOT NULL,
    body_text   TEXT NOT NULL,
    PRIMARY KEY (doc_id, section_id)
);
```

### 内存向量

`DocVector(doc_id, text, vector)` 和 `SectionVector(doc_id, section_id, text, vector)`，按 `doc_id` 去重重写。

`section_id` 严格匹配 `^\d+(\.\d+)*$`。Chapter 0 用 `0.1`/`0.2`/`0.3` 表示摘要/前言/引言。

## 入库流程详解

`pipeline/ingest.py: ingest_markdown` 做这些事：

1. **解析 markdown**：`parse_markdown()` 切章节、固化 `section_id`、提取层级标题
2. **抽 file_topic**：取第一个 `#` 标题的文本（≤ 120 字）
3. **推 doc_title**：第一个 level=1 的章节标题，或文件名 stem
4. **写 `documents`**：按 `doc_key` upsert
5. **写 `sections`**：先 `DELETE WHERE doc_id=?` 再批量 INSERT
6. **生成 doc_vectors**：
   - `base` 文本：`filename\nfile_topic\ndoc_title`
   - 多个 `alias` 文本：从 `filename / file_topic / doc_title` 中拆出 ≥ 2 字符的 token，最多 8 个
   - 每条独立 embed，写入 `vector_store.doc_vectors`
7. **生成 section_vectors**：每个章节按层级拼标题（按方案 4.4，**不**放 filename/topic 避免压过差异）
   - L1：`l1_title`
   - L2：`l1_title\nl2_title`
   - L3：`l1_title\nl2_title\nl3_title`

## 检索流程详解

`pipeline/retrieve.py: retrieve` 是严格的 5 步单链：

```
embed(query)
  ↓
[Step 1] doc_vectors topK 召回 + 按 doc_id 聚合（取最高分）+ 词法 rerank
  ↓
[Step 2] parse_anchor(query) → section_id 或 INSUFFICIENT
  ↓
[Step 3] 锚点存在？──是──→ 读 sections 返回 (section_method=anchor_exact)
  ↓ 否
[Step 4] section_vectors 在该 doc 内 topK 召回 + 聚合 + 词法 rerank
  ↓
[Step 5] 读 sections 返回 (section_method=fallback_vectors)
```

**doc 聚合**：同一 `doc_id` 可能有多条 alias 向量，topK 里同一个 doc 占多个位置，所以要按 `doc_id` 聚合取最高分再排序。

**词法 rerank**：在向量分数基础上，用 `query` 和 candidate text 的 token 交集做二次排序（中文支持单字 + bigram）。这是方案 7.2/7.5 "LLM 重排"的最小本地实现。

**存在性校验**：解析出的 `section_id` 必须在 SQLite 里真的存在；不存在就走兜底。这避免锚点解析"看起来合理但实际章节缺失"。

## 锚点解析规则

`parsing/anchor.py: parse_anchor` 按这个优先级匹配：

| 优先级 | 输入示例 | 输出 | 触发条件 |
|--------|----------|------|----------|
| 1 | `摘要讲了什么` / `abstract` | `0.1` | Chapter 0 关键词 |
| 1 | `前言` / `序言` / `preface` / `序` | `0.2` | 同上 |
| 1 | `引言` / `导言` / `introduction` | `0.3` | 同上 |
| 2 | `2.1`、`3.2.1`、`2-1` | `2.1`、`3.2.1`、`2.1` | 显式数字路径 |
| 3 | `第2章第3节第1小节` / `第二章第三节` | `2.3.1` / `2.3` | 中文章节链 |
| 4 | `第3章` / `第三篇` | `3` | 单独的章/篇 |
| ∅ | 其他全部情况 | `INSUFFICIENT` | 无法唯一定位 |

**故意返回 INSUFFICIENT 的情况：**

- `实验设置这一节讲了什么`：只有关键词没编号，可能多处都有"实验设置"
- `第一节讲了什么`：没有"第几章"上下文，且无对话历史
- `（一）实验设置`：括号编号在 PDF 里多层都可能出现，无法反推

设计原则：**宁可 INSUFFICIENT 也不硬猜**，让向量兜底接手。

## Markdown 解析规则

`parsing/markdown.py: parse_markdown` 同时支持三类标题：

1. **ATX 标题**：`# 1 方法`、`## 2.1 实验设置`，level 直接看 `#` 个数
2. **数字前缀行**（无 `#`）：`2.1 实验设置`、`2-1) 训练细节`
3. **中文章节前缀**：`第2章 方法`、`第二节 数据`

**section_id 分配：**

- 标题里有显式数字 → 直接用（`2.1` → `2.1`）
- 没显式数字 → 按层级计数器自增
- 冲突时自动 `+1` 直到唯一

**Chapter 0 识别：**

第一个 H1 之前的内容会被识别为：

- 出现 `摘要` / `abstract` → `0.1`
- 出现 `前言` / `序言` / `preface` / `序` → `0.2`
- 出现 `引言` / `导言` / `introduction` → `0.3`

支持两种 PDF 风格：marker 行单独成行（按 marker 切分多个 0.x），或整段无分隔（识别为单个 0.x）。

**文档级 H1 跳过：**

如果第一个 H1 没编号但后续有编号 H1，把它视为"文档标题"，不固化为可检索章节。

## 诊断与排查

每次 `retrieve()` 都返回 `diagnostics`：

```python
{
    "query": "...",
    "doc_candidates": [{"doc_id": 1, "score": 0.85}, ...],
    "anchor_section_id": "2.1",  # 或 "INSUFFICIENT"
    "section_candidates": [{"section_id": "2.1", "score": 0.72}, ...],  # 走兜底时才有
}
```

排错思路：

| 现象 | 看什么 | 可能原因 |
|------|--------|----------|
| `found=False`、无 doc_candidates | doc_vectors 为空 | 没入库 / vector_store 是新进程的 |
| doc 选错 | doc_candidates | 文件名/topic/alias 没覆盖到用户用词；试调高 `doc_top_k` |
| anchor_section_id 是 INSUFFICIENT 但本应解析 | query 文本 | 看 `parsing/anchor.py` 规则；可能是用了不支持的格式 |
| `section_method=anchor_exact` 但 section 错 | sections 表 | markdown 解析的 section_id 跟用户预期对不上 |
| 走 fallback 但选错章节 | section_candidates | 章节标题区分度不够；hash embedding 是关键词驱动 |

## 测试

```bash
pytest -q
```

包含三组：

- `test_anchor.py`：锚点解析的核心 case 和 INSUFFICIENT 边界
- `test_markdown.py`：section_id 固化、Chapter 0
- `test_retrieval.py`：端到端（入库 → 锚点路径 + 兜底路径都跑一遍）

## 已知限制

这是练手项目，下面这些都是**故意**没做的：

- **向量不持久化**：`VectorStore` 只在内存。要 CLI 跨进程查询，得把它存进 SQLite（schema 简单，自己加）。
- **hash embedding 没语义**：`HashingEmbedder` 本质是 token 计数 + L2 归一，对"实验配置 vs 实验设置"这种近义词无能为力。真用得换 OpenAI 兼容 API。
- **没有 LLM**：方案里 7.2/7.5 提到 LLM rerank，这里用本地词法 rerank（token 交集）替代。
- **没有 Milvus**：方案里写了 Milvus，这里用内存 list + cosine 暴力遍历。文档量小够用。
- **没有真实 PDF benchmark**：仓库里有 `examples/sample.md` 一个文件演示。要做真实评测自己接 PyMuPDF 之类。

如果要把这些补上，每一项都是独立改动，不会动到现有架构。

## License

MIT, see [LICENSE](LICENSE).
