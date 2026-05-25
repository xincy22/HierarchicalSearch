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
- [Roadmap](#roadmap)

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

向量默认在内存里，所以**最简用法是入库 + 查询同一个进程内**。要跨进程
查询，调用 `vector_store.persist_to(doc_store)` 落盘，下次起进程后用
`vector_store.load_from(doc_store)` 加载即可（CLI 已经这么做）。

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

`ingest` 会把文档和向量都写入 SQLite，`query` 会自动从 SQLite 加载向量，
所以这两个命令可以独立跨进程使用：

```bash
python -m hierarchical_search --db hs.db init-db
python -m hierarchical_search --db hs.db ingest examples/sample.md
python -m hierarchical_search --db hs.db query "sample 2.1 讲了什么"
```

注意 `--db` 必须在子命令之前。

需要"边入库边查、不落盘"的快速演示，用 `demo` 子命令：

```bash
python -m hierarchical_search --db :memory: demo examples/sample.md "sample 2.1 讲了什么"
```

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
retrieve(
    query, embedder, doc_store, vector_store,
    doc_top_k=20, section_top_k=50,
    min_doc_score=0.05, min_doc_overlap=1,
    min_section_score=0.05, min_section_overlap=1,
) -> RetrievalResult
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
| `reject_reason` | 拒答原因，见下表；`found=True` 时为 `None` |
| `diagnostics` | 候选列表 + 锚点解析结果 |

`reject_reason` 可能取值：

| 值 | 含义 |
|----|------|
| `no_doc_vectors` | 向量库为空（没入库 / 没 load） |
| `low_doc_confidence` | 多个候选文档但都既不命中向量也无词法重叠 |
| `no_section_vectors` | 已选 doc 下无 section 向量（异常状态） |
| `low_section_confidence` | fallback 章节分数和词法重叠都太低 |

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
    persist_to(doc_store)        # 写入 SQLite
    load_from(doc_store)         # 从 SQLite 整体加载（覆盖内存）
```

库用法默认是纯内存的；要跨进程查询时调用 `persist_to` / `load_from`，CLI 已经这么做。

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
| `found=False`, `reject_reason=no_doc_vectors` | 是否 ingest 过；CLI 是否调了 `load_from` | 库未入库；或者库内代码忘了 `load_from` |
| `found=False`, `reject_reason=low_doc_confidence` | doc_candidates 的 score 和 lexical_overlap | 用户没给文档线索，按设计拒答；可调低 `min_doc_score` / `min_doc_overlap` |
| `found=False`, `reject_reason=low_section_confidence` | section_candidates | 兜底章节信号太弱，按设计拒答；同上可调阈值 |
| doc 选错 | doc_candidates | 文件名/topic/alias 没覆盖到用户用词；试调高 `doc_top_k` |
| anchor_section_id 是 INSUFFICIENT 但本应解析 | query 文本 | 看 `parsing/anchor.py` 规则；可能是用了不支持的格式 |
| `section_method=anchor_exact` 但 section 错 | sections 表 | markdown 解析的 section_id 跟用户预期对不上 |
| 走 fallback 但选错章节 | section_candidates | 章节标题区分度不够；hash embedding 是关键词驱动 |

## 测试

```bash
pytest -q
```

包含四组：

- `test_anchor.py`：锚点解析的核心 case、INSUFFICIENT 边界、英文大小写、`序` 单字误伤
- `test_markdown.py`：section_id 固化、Chapter 0（含 ATX `# 摘要` / `# Abstract`）
- `test_retrieval.py`：端到端（锚点 + 兜底）、低置信拒答、向量持久化往返
- `test_cli.py`：CLI demo 同进程、ingest+query 跨调用、空库不崩溃

## 已知限制

这是练手项目，下面这些都是**故意**没做的：

- **hash embedding 没语义**：`HashingEmbedder` 本质是 token 计数 + L2 归一，对"实验配置 vs 实验设置"这种近义词无能为力。真用得换 OpenAI 兼容 API。
- **没有 LLM**：方案里 7.2/7.5 提到 LLM rerank，这里用本地词法 rerank（token 交集）替代。
- **没有 Milvus**：方案里写了 Milvus，这里用内存 list + cosine 暴力遍历，向量持久化用 JSON 列。文档量小够用。
- **没有真实 PDF benchmark**：仓库里有 `examples/sample.md` 一个文件演示。要做真实评测自己接 PyMuPDF 之类。

如果要把这些补上，每一项都是独立改动，不会动到现有架构。

## Roadmap

按价值/复杂度从高到低排：

- **可插拔 Embedder**：把 `HashingEmbedder` 抽成 `Embedder` 协议（`embed(text) / embed_many(texts) / dim`），加一个 OpenAI 兼容实现。注意切换 embedder 后旧 SQLite 里的向量会失效，需要 re-ingest 或在 `documents` / 向量表上加 embedder 标识做兼容判断。
- **更好的章节兜底**：当前 fallback 只看层级标题拼接，对"实验设置 vs 实验配置"这种近义词无能为力。换语义 embedder 后再考虑加 title bigram 或 BM25 二路。
- **批量 ingest 与 watch 模式**：`ingest <dir>` 递归入库 + `--watch` 监听文件变更，方便对接笔记目录。
- **真实 PDF benchmark**：接 PyMuPDF / `unstructured`，跑一份带标注的小数据集，统计锚点路径和 fallback 路径的命中率，验证默认阈值是否合理。
- **更精细的拒答阈值**：现在 `min_doc_score` / `min_section_score` 是单值兜底，可以做成相对差（top-1 vs top-2 score gap）来减少边缘 case 误拒。
- **替换暴力 cosine**：文档量上千之后线性扫不行，可以接 Milvus 或 sqlite-vss。当前 schema 已经是 JSON 列，迁移成本可控。

## License

MIT, see [LICENSE](LICENSE).
