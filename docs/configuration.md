# Configuration

项目会自动读取根目录 `.env`（也可用 `HS_ENV_FILE` 指定 env 文件），详见 `hierarchical_search/app/config.py`。

## 推荐的 `.env` 模板

以 GLM（OpenAI 兼容 API）+ Milvus 为例：

```env
# SQL (SQLite for local dev; switch to MySQL for prod)
HS_DATABASE_URL=sqlite:///hierarchical_search.db

# Vector backend
HS_VECTOR_BACKEND=milvus
HS_MILVUS_URI=http://127.0.0.1:19530

# Embedding / LLM
HS_EMBEDDING_BACKEND=hash
HS_LLM_BACKEND=openai

OPENAI_API_KEY=...
HS_OPENAI_BASE_URL=https://open.bigmodel.cn/api/paas/v4/
HS_OPENAI_CHAT_MODEL=GLM-4.7-Flash

# Retrieval tuning
HS_DOC_TOP_K=20
HS_SECTION_TOP_K=50
```

如果只想“本地完全离线跑通”，可以：

```env
HS_VECTOR_BACKEND=local
HS_EMBEDDING_BACKEND=hash
HS_LLM_BACKEND=rule
```

## 环境变量说明（常用）

- `HS_DATABASE_URL`：SQLAlchemy URL（SQLite/MySQL 等）
- `HS_VECTOR_BACKEND`：`local` / `milvus` / `memory`
- `HS_LOCAL_VECTOR_PATH`：`local` 向量库文件路径
- `HS_MILVUS_URI`：Milvus 地址（例如 `http://127.0.0.1:19530`）
- `HS_EMBEDDING_BACKEND`：`hash` / `openai`
- `HS_LLM_BACKEND`：`rule` / `openai`
- `OPENAI_API_KEY`：远程后端 key
- `HS_OPENAI_BASE_URL`：OpenAI 兼容 API base_url（也支持 `OPENAI_BASE_URL`）
- `HS_OPENAI_CHAT_MODEL`：chat 模型名
- `HS_OPENAI_EMBEDDING_MODEL`：embedding 模型名
- `HS_PROMPT_FILE`：自定义 prompt YAML

## 关于 embedding 维度（重要）

- 本地 `hash` embedding 维度由 `HS_EMBEDDING_DIM` 决定（默认 384）
- 若使用远程 embedding（`HS_EMBEDDING_BACKEND=openai`），请确保：
  - `HS_EMBEDDING_DIM` 与实际模型输出维度一致
  - Milvus collection 维度与之匹配

不一致会导致：

- `local` 后端：相似度计算被截断/失真（`zip(a,b)`）
- `milvus` 后端：写入或搜索阶段直接报维度错误

