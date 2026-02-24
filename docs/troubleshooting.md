# Troubleshooting

## 1. 查询找不到（`found=false`）

排查顺序建议：

1. doc 定位是否失败：`diagnostics.doc_candidates` 是否为空/是否命中正确 doc
2. anchor 是否解析出 `section_id`：`diagnostics.anchor_section_id`
3. 章节是否存在：如果解析出了 `2.1` 但不存在，说明入库时 `section_id` 固化不一致或文档解析失败
4. 兜底向量是否为空：`section_vectors_empty` 通常是没入库成功或 doc_id 过滤错

## 2. 锚点解析不符合预期

锚点解析遵循“保守不硬猜”，常见行为：

- `第X节` 但没有 `第X章`：会返回 `INSUFFICIENT`（避免歧义）
- `（一）` / `(1)` 这种前缀：默认认为歧义，走向量兜底

实现见：`hierarchical_search/parsers/anchor.py`

## 3. Milvus 报维度不匹配

原因：

- `HS_EMBEDDING_DIM` 与 embedding 实际输出维度不一致
- Milvus collection 在旧维度下创建过，后来改了 embedding 维度

建议：

- 先用 `hash` embedding 跑通流程
- 维度确定后再建 collection
- 需要重置时：`docker compose -f docker-compose.milvus.yaml down -v`

## 4. MySQL 连接失败

项目通过 SQLAlchemy 连接 MySQL；你需要额外安装驱动：

- `pip install pymysql`
- `HS_DATABASE_URL=mysql+pymysql://user:password@host:3306/dbname`

## 5. 远程 LLM 限流（429）

远程调用是 best-effort：

- 发生 429 时会自动停止继续请求远程 LLM，并降级为本地 rule 路径
- 这样能保证检索单链可用，但远程能力（如 rerank）会被关闭

如果你想让它稳定使用远程：

- 降低并发/请求频率
- 或者在 benchmark 中减少 runs / limit cases

