# Memo Changelog

## v0.9.0-alpha (2026-07-16)

### 新增：Context Space
- 新增 `spaces` / `space_aliases` / `space_memories`。
- `sessions`、`todos` 支持绑定 `space_id`。
- Engine 新增 `space_create/list/get/update/detect/bind/unbind/profile/recall/archive/restore/alias` 等接口。
- MCP 新增 Space 相关工具：`space_create`、`space_list`、`space_activate`、`space_deactivate`、`space_profile`、`space_recall`、`space_detect`。

### 新增：Dashboard Svelte 门面
- 新增 Svelte + Vite 前端项目。
- 新增 Overview、Memories、Spaces、Persona、Todos、Graph 页面。
- `memo_dashboard.py` 优先服务 `dashboard/dist`，旧内嵌页面作为 fallback。

### 新增：记忆治理
- 新增 migration `011_memory_governance.sql`。
- `memory_units` 新增 `status`、`user_weight`、`pinned`、`user_note`、`updated_at`。
- 新增 `memory_audit_logs`。
- Dashboard 支持标重要、错误、过期、静默、软删除、恢复。
- MCP 新增 `memory_govern`。

### 新增：发布工程
- 新增 `scripts/doctor.py` 只读环境自检。
- 新增 `scripts/build_release.py` 安全打包，默认排除 `.env`、真实数据库、日志、备份、node_modules。
- `start_all.bat` 写入 PID 文件。
- `stop_all.bat` 优先按 PID 停止服务。
- 新增 `upgrade.bat`，引导单进程升级。
- `scripts/init_db.py` 默认只做初始化/迁移，不再写入测试记忆；写入自检需显式 `--self-test`。

### 体验优化与发布实测
- 记忆卡片标题支持打开详情，详情展示摘要、原文、标签和治理记录。
- 记忆类型与状态中文化，适配中文用户。
- 错误、过期、静默、软删除、降低权重等治理操作增加确认与撤回入口。
- Space 归档增加说明与恢复路径，归档后自动显示归档列表，避免“找不到”。
- 补充搜索、创建、保存、扫描、归类确认等按钮加载态和骨架屏。
- 已生成发布包并在干净目录完成初始化 / migration / doctor 自检。

### 安全与测试
- `MEMO_ENV=production/development/test`。
- test/development 使用隔离数据库。
- production pending migration 前自动备份。
- `test.bat` 强制 `MEMO_ENV=test`。

---

## v0.7.0 (2026-07-14)

### 新增：人格 + 待办 + Bridge
- 人格画像 10 维断言。
- 待办管理与风险检测。
- Bridge inbox 导出/导入。
- MCP 工具扩展到记忆、人格、待办、导入导出等。

---

## v0.2.0 (2026-06-29)

### 新增：上下文感知提取
- `remember_conversation` 新增 `context_rounds` 参数（默认 3）。
- 提取记忆时自动回顾同会话最近 N 轮对话原文。
- Prompt 增加上下文区域，摘要规则明确要求引用有补充价值的上下文。
- 涉及文件：`memo/core/engine.py`、`memo/extraction/extractor.py`。

### 重构：包结构规范化
- 按 `architecture.md` 重建标准 Python 包结构。
- 补全 `memo/models` 模块。
- `config.py` 引入 `_PROJECT_ROOT` 常量，适配新包层级，路径全动态化。
- `run_mcp.py` 路径修正。

---

## v0.1.0 (2026-06-27)

### 初始发布
- 三层记忆架构（L0 热/L1 温/L2 冷）。
- 六维存储模型。
- 三通道检索（向量语义 + BM25 全文 + 赫布扩散激活）。
- RRF 融合排序。
- 赫布学习与 Bjork 双强度遗忘。
- LLM/jieba 双模式特征词提取。
- MCP Server、Web 看板、自动同步守护进程。
