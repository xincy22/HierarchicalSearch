# HierarchicalSearch

按 `层级检索.md` 方案实现的单链层级检索项目：

`doc_id -> section_id(anchor优先, vector兜底) -> body_text`

## 这是什么

适用场景：

- 用户问题带明确“章节定位信号”（`2.1` / `第2章第3节` / 摘要/引言等），希望稳定命中对应段落
- 用户没有编号但指向标题关键词（“实验设置/相关工作/结论”），锚点不足时用章节标题向量兜底定位 `section_id`

非目标：

- 多轮对话的“上一节/这一节”
- 跨文档事实问答（这是通用 RAG 的职责，不由本模块主导）

## 快速导航

- 架构与单链流程：`architecture.md`
- 配置与环境变量：`configuration.md`
- Milvus 部署与冒烟测试：`milvus.md`
- Benchmark 与真实评测建议：`benchmark.md`
- 常见问题排障：`troubleshooting.md`

## 本地运行（最小闭环）

```bash
python -m hierarchical_search init-db
python -m hierarchical_search ingest examples/sample.md
python -m hierarchical_search query "demo 文档 2.1 讲了什么"
```
