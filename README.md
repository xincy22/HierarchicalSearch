# HierarchicalSearch

按 `层级检索.md` 方案实现的单链层级检索项目：

`doc_id -> section_id(anchor优先, vector兜底) -> body_text`

适用场景：

- 用户问题带“章节定位信号”（`2.1` / `第2章第3节` / 摘要/引言等），希望稳定命中对应段落
- 用户没有明确编号但指向标题关键词（“实验设置/相关工作/结论”），用章节标题向量兜底定位到 `section_id`

非目标：

- 多轮对话的“上一节/这一节”
- 跨文档事实问答（这是通用 RAG 的职责，不由本模块主导）

## 1. 功能覆盖

- 两级索引
  - `doc_vectors`：文档级定位 `doc_id`
  - `section_vectors`：章节级 fallback 定位 `section_id`
- MySQL/SQLite 章节表
  - `sections(doc_id, section_id)` 联合主键
  - 可直接返回正文 `body_text`
- 在线检索单链
  - 文档定位
  - 锚点解析（`section_id` / `INSUFFICIENT`）
  - 存在性校验
  - 向量 fallback
  - 正文读取
- 诊断信息
  - 返回 doc/section 的命中方式和候选信息，便于排障

## 2. 安装

```bash
pip install -r requirements.txt
```

推荐开发安装（可用 `hierarchical-search` 命令）：

```bash
python -m pip install -e ".[dev]"
```

可选：

```bash
pip install ".[openai]"   # OpenAI embedding + LLM
pip install ".[milvus]"   # Milvus vector backend
```

### 2.1 使用 `.env` 管理环境变量

项目启动时会自动读取根目录 `.env`（也可用 `HS_ENV_FILE` 指定文件路径）。

```bash
cp .env.example .env
```

Windows（PowerShell）：

```powershell
Copy-Item .env.example .env
```

然后在 `.env` 中填写你的配置（例如 `OPENAI_API_KEY`、`HS_OPENAI_BASE_URL`、`HS_OPENAI_CHAT_MODEL`）。

## 3. 快速开始

下面以默认的“SQLite + 本地向量（local）+ rule/hash 后端”做一个可复现的最小闭环。

### 3.1 初始化数据库

```bash
python -m hierarchical_search init-db
```

默认是 SQLite：

- SQL 数据：`hierarchical_search.db`
- 本地向量：`hierarchical_vectors.db`

### 3.2 入库 markdown（将章节固化为 `section_id`）

```bash
python -m hierarchical_search ingest examples/sample.md
```

入库阶段会做：

- Markdown 章节解析与 `section_id` 固化（数字路径：`1` / `2.1` / `3.2.1`）
- 写入 `documents` / `sections` 表（最终能直接返回 `body_text`）
- 写入 `doc_vectors` / `section_vectors`（用于 doc/section 两级向量定位）

### 3.3 查询（锚点优先，向量兜底）

```bash
python -m hierarchical_search query "某某论文 2.1 讲了什么"
```

会输出 JSON，包括：

- `found`, `doc_id`, `section_id`
- `title_text`, `body_text`
- `doc_method`, `section_method`
- `diagnostics`

### 3.4 CLI 参数

所有子命令都支持这些参数（也可用环境变量配置）：

- `--database-url`
- `--vector-backend`：`local` / `memory` / `milvus`
- `--local-vector-path`
- `--embedding-backend`：`hash` / `openai`
- `--llm-backend`：`rule` / `openai`
- `--prompt-file`

例：单次查询临时切换后端：

```bash
python -m hierarchical_search query "2.1 讲了什么" --llm-backend rule --vector-backend local
```

## 4. 配置与后端切换

通过环境变量或 CLI 参数控制。

### 4.1 常用环境变量

最常用的一组（更多见 `hierarchical_search/app/config.py`）：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `HS_DATABASE_URL` | `sqlite:///hierarchical_search.db` | SQL 存储（SQLite/MySQL 等 SQLAlchemy URL） |
| `HS_VECTOR_BACKEND` | `local` | 向量后端：`local`(SQLite) / `milvus` / `memory` |
| `HS_LOCAL_VECTOR_PATH` | `hierarchical_vectors.db` | `local` 向量库文件路径 |
| `HS_EMBEDDING_BACKEND` | `hash` | embedding：`hash`(本地) / `openai`(远程) |
| `HS_EMBEDDING_DIM` | `384` | embedding 维度。注意与实际 embedding 输出一致 |
| `HS_LLM_BACKEND` | `rule` | LLM：`rule`(本地规则) / `openai`(OpenAI 兼容 API) |
| `OPENAI_API_KEY` |  | 远程 LLM/embedding 的 API key |
| `HS_OPENAI_BASE_URL` |  | OpenAI 兼容 API base_url（也支持 `OPENAI_BASE_URL`） |
| `HS_OPENAI_CHAT_MODEL` | `gpt-4o-mini` | chat 模型名（例如 `GLM-4.7-Flash`） |
| `HS_OPENAI_EMBEDDING_MODEL` | `text-embedding-3-small` | embedding 模型名 |
| `HS_PROMPT_FILE` |  | 自定义 prompt YAML 路径 |
| `HS_DOC_TOP_K` | `20` | doc 向量召回 topK |
| `HS_SECTION_TOP_K` | `50` | section 向量召回 topK |
| `HS_LLM_RERANK_ENABLED` | `true` | 是否允许用远程 LLM 做重排（必要时会自动降级） |
| `HS_ENV_FILE` | `.env` | 指定读取的 env 文件路径 |

> 重要：如果使用 `HS_EMBEDDING_BACKEND=openai`，请把 `HS_EMBEDDING_DIM` 设置为该 embedding 模型实际输出维度；否则相似度计算会失真（或在 Milvus 入库时报错）。

### 4.2 MySQL

```bash
set HS_DATABASE_URL=mysql+pymysql://user:password@127.0.0.1:3306/hierarchical_search
python -m hierarchical_search init-db
```

MySQL 需要安装对应驱动（例如 `pip install pymysql`）。

`sql/schema.sql` 提供了 MySQL DDL 版本。

### 4.3 Milvus（推荐：数据量大时）

Milvus（2.x）通常依赖 etcd + MinIO/S3。仓库提供了一个最小可用的 compose：`docker-compose.milvus.yaml`。

```bash
docker compose -f docker-compose.milvus.yaml up -d

# then switch vector backend to Milvus (recommended via .env)
# HS_VECTOR_BACKEND=milvus
# HS_MILVUS_URI=http://127.0.0.1:19530

python -m hierarchical_search ingest examples/sample.md
```

停止：

```bash
docker compose -f docker-compose.milvus.yaml down
```

重置数据（会删除 volumes）：

```bash
docker compose -f docker-compose.milvus.yaml down -v
```

### 4.4 OpenAI / GLM（OpenAI 兼容 API）

项目通过 `openai` 官方 Python SDK 调用 OpenAI 兼容 API，并支持自定义 `base_url`。

例如用 GLM（仅示例，key 自行填写）：

```env
HS_LLM_BACKEND=openai
OPENAI_API_KEY=...
HS_OPENAI_BASE_URL=https://open.bigmodel.cn/api/paas/v4/
HS_OPENAI_CHAT_MODEL=GLM-4.7-Flash
```

> 远程调用为 best-effort：当发生限流（429）等错误时，会自动降级为本地 `rule` 逻辑保证主流程可用。

### 4.5 统一 Prompt YAML（便于调试）

默认 prompt 文件：`hierarchical_search/ai/prompts.yaml`

可通过环境变量覆盖：

```bash
set HS_PROMPT_FILE=./my_prompts.yaml
```

或 CLI 覆盖：

```bash
python -m hierarchical_search query "2.1讲了什么" --llm-backend openai --prompt-file ./my_prompts.yaml
```

## 5. 数据规模与性能建议

- `HS_VECTOR_BACKEND=local`（SQLiteVectorStore）会在查询时遍历向量并在本地计算余弦相似度，适合开发/CI/小数据集；大规模请切 Milvus。
- SQL 存储默认是 SQLite；并发写入和大数据量场景建议切 MySQL/PostgreSQL（目前文档给的是 MySQL）。
- 召回规模可用 `HS_DOC_TOP_K` / `HS_SECTION_TOP_K` 调整；在噪声较大的真实文档上，适当提高 topK 通常能提升召回稳定性（但会增加重排成本）。

## 6. Benchmark

仓库内置一个“合成语料”benchmark：`benchmarks/run_benchmark.py`，用于快速回归（不代表真实 PDF 的解析噪声）。

```bash
python benchmarks/run_benchmark.py --runs 1 --warmup 4 --llm-backend rule --embedding-backend hash
```

输出为 JSON（准确率 + 时延分位数 + QPS），可用 `--output-json` 写文件。

> 想做更贴近真实场景的评测：建议用真实 PDF 转 markdown（如 PyMuPDF/pdfplumber），构建小规模金标 QA，再跑同样的 `ingest -> query` 链路。

## 7. 测试

```bash
pytest -q
```

Milvus 冒烟测试（需要启动 Milvus 并安装 `pymilvus`）：

```bash
pip install ".[milvus]"
docker compose -f docker-compose.milvus.yaml up -d

HS_RUN_MILVUS_TESTS=1 HS_MILVUS_URI=http://127.0.0.1:19530 pytest -q
```

## 8. 目录结构

```text
hierarchical_search/
  app/                      # 运行入口与装配
    config.py
    factory.py
    cli.py
  services/                 # 核心业务流程
    ingestion.py            # 离线入库流水线
    retrieval.py            # 在线单链检索
  storage/                  # 数据存储层
    models.py               # documents/sections ORM
    db.py                   # DB与Repository
    vector_store/
      sqlite.py
      milvus.py
      in_memory.py
  ai/                       # 模型/提示词层
    embedding.py            # Hashing/OpenAI embedding
    llm.py                  # Rule/OpenAI LLM逻辑（section_id输出约束）
    prompts.py              # YAML prompt 加载与模板渲染
    prompts.yaml            # 统一 prompt 配置
  parsers/
    anchor.py               # 查询锚点解析 -> section_id/INSUFFICIENT
    markdown.py             # markdown章节解析与section_id固化
tests/
sql/schema.sql
```

## 9. 与方案映射

- 文档表：`documents`
- 章节表：`sections`，主键 `(doc_id, section_id)`
- 向量集合：
  - `doc_vectors`
  - `section_vectors`
- 在线流程实现于 `hierarchical_search/services/retrieval.py`
- 锚点规则与 `INSUFFICIENT` 实现于 `hierarchical_search/parsers/anchor.py`

## 10. License

MIT, see `LICENSE`.

## 11. Contributing

See `CONTRIBUTING.md`.

## 12. Security

See `SECURITY.md`.

## Docs

More details: `docs/index.md`.

### Build Docs (MkDocs)

```bash
python -m pip install -e ".[docs]"
mkdocs serve
```
