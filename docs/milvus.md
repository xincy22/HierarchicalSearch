# Milvus

项目支持 `HS_VECTOR_BACKEND=milvus`，代码位于 `hierarchical_search/storage/vector_store/milvus.py`。

## 1. 用 Docker Desktop + WSL 启动（推荐）

仓库提供了最小可用的 compose：`docker-compose.milvus.yaml`（包含 `etcd + minio + milvus`）。

启动：

```bash
docker compose -f docker-compose.milvus.yaml up -d
docker compose -f docker-compose.milvus.yaml ps
```

停止：

```bash
docker compose -f docker-compose.milvus.yaml down
```

清空数据（会删除 volumes）：

```bash
docker compose -f docker-compose.milvus.yaml down -v
```

## 2. 项目侧配置

`.env`：

```env
HS_VECTOR_BACKEND=milvus
HS_MILVUS_URI=http://127.0.0.1:19530
```

然后重新 ingest（会写入 Milvus collection）：

```bash
python -m hierarchical_search ingest examples/sample.md
```

## 3. 连通性检查

Python 侧快速检查：

```bash
python - <<'PY'
from pymilvus import connections
connections.connect(uri="http://127.0.0.1:19530")
print("milvus_ready")
PY
```

## 4. 冒烟测试

仓库内置 Milvus 冒烟测试：`tests/test_milvus_smoke.py`

```bash
pip install ".[milvus]"
HS_RUN_MILVUS_TESTS=1 HS_MILVUS_URI=http://127.0.0.1:19530 pytest -q tests/test_milvus_smoke.py
```

## 5. 常见问题

### 5.1 Milvus 启动后立刻退出

通常是 etcd/minio 未启动或连接不上。用 compose（带依赖）启动即可。

### 5.2 维度不匹配

若你切换了 embedding 模型，记得同步：

- `HS_EMBEDDING_DIM`
- Milvus collection 的 `dim`

建议在“确定 embedding 维度”后再建库/入库；不确定时先用 `hash` embedding 跑通链路。
