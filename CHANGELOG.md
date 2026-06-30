# Memo Changelog

## v0.2.0 (2026-06-29)

### 新增：上下文感知提取
- `remember_conversation` 新增 `context_rounds` 参数（默认 3）
- 提取记忆时自动回顾同会话最近 N 轮对话原文
- LLM 自行判断前情是否有关联，有则纳入摘要（如「基于之前对 PostgreSQL 的讨论，用户决定...」）
- Prompt 增加上下文区域，摘要规则明确要求引用有补充价值的上下文
- 涉及文件：`memo/core/engine.py`、`memo/extraction/extractor.py`

### 重构：包结构规范化
- 按 `architecture.md` 重建标准 Python 包结构（memo/core/store/utils/models/mcp/retrieval/extraction/lifecycle）
- 补全 `memo/models` 模块（FeatureTag/MemoryUnit/FeatureRelation/Session/TagMention/GlobalMemorySnapshot）
- `config.py` 引入 `_PROJECT_ROOT` 常量，适配新包层级，路径全动态化
- `run_mcp.py` 路径修正

### 修复
- FeatureTag 补充 `is_dormant` 字段
- MemoryUnit 补充 `created_at` 字段
- config.py 路径适配新包结构

---

## v0.1.0 (2026-06-27)

### 初始发布
- 三层记忆架构（L0 热/L1 温/L2 冷）
- 六维存储模型（会话/特征词/关系/记忆单元/TagMention/快照）
- 三通道检索（向量语义 + BM25 全文 + 赫布扩散激活）
- RRF 融合排序
- 赫布学习（边权重随共激活增长）
- Bjork 双强度遗忘（检索强度自动衰减，三维度休眠）
- 双时序冲突处理（valid_from/valid_until + is_superseded）
- LLM/jieba 双模式特征词提取
- MCP Server（8 个核心工具，stdio 协议）
- Web 看板（统计卡片 + 特征词云 + 记忆列表 + 详情弹窗）
- 自动同步守护进程（memo_watcher.py）
- 零 API 依赖运行
- 技术栈：Python 3.11+、SQLite + FTS5、BGE-small-zh-v1.5、MCP SDK
