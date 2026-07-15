# Memo 项目交接文档

> 2026-07-14 · V0.7.0 · schema v5 · ~790 条记忆 · 39 条人格断言

---

## 一、项目路径

```
D:\个人\Hanako项目文件\Memo_V0.1.0\
├── memo/                    # 核心包
│   ├── core/                # engine.py, config.py
│   ├── store/               # database.py, graph_store.py, memory_store.py, vector_store.py, migrations/
│   ├── extraction/          # extractor.py, gating.py, change_detector.py
│   ├── lifecycle/           # forgetting.py, consolidation.py, snapshot.py
│   ├── persona/             # extractor.py, router.py, deviation.py（V0.6）
│   ├── todo/                # manager.py（V0.7）
│   ├── retrieval/           # graph_search.py, fusion.py
│   ├── mcp/                 # server.py（18 个 MCP 工具）
│   └── utils/               # llm.py, embedding.py, logger.py
├── scripts/                 # 运维脚本 + Dashboard
│   ├── memo_dashboard.py    # 看板（图谱/列表/人格/待办）
│   ├── memo_watcher.py      # 守护进程（会话同步 + inbox + 人格刷新 + 风险检测）
│   ├── import_sessions.py   # 历史会话导入（断点续传）
│   ├── run_mcp.py           # MCP Server 启动脚本
│   ├── start_all.bat        # 一键启动
│   └── stop_all.bat         # 一键停止
├── docs/                    # 设计 + 部署文档
│   ├── V0.6-人格引擎-架构设计.md
│   ├── V0.7-待办管理-设计方案.md
│   └── deploy-guide.md, setup-guide.md, testing-guide.md, ...
├── data/                    # 数据库 + 备份
│   ├── memo.db              # 主数据库（不提交 Git）
│   └── backups/             # 备份目录
├── .env                     # API Key + 配置（不提交 Git）
├── SKILL.md                 # Agent Skill 提示词
├── AGENT_PROMPT.md          # Agent 系统提示词
├── README.md                # 部署文档
└── HANDOFF.md               # 本文档
```

---

## 二、当前状态

| 指标 | 数值 |
|------|:---:|
| 记忆数 | ~790 条 |
| 人格断言 | 39 条（10 维全覆盖） |
| 待办 | 0 条进行中，1 条已完成 |
| schema 版本 | v5 |
| MCP 工具数 | 18 个 |

---

## 三、MCP 工具清单（18 个）

### 记忆类
| 工具 | 用途 |
|------|------|
| `memo_remember` | 写入记忆（支持 agent_name 追溯来源） |
| `memo_recall` | 三通道混合检索（向量+FTS5+图谱） |
| `memo_export` | Bridge 导出（Agent 对话 → inbox） |
| `memo_import_sessions` | 批量导入历史会话 |
| `memo_import_status` | 查看导入进度 |

### 会话/统计类
| 工具 | 用途 |
|------|------|
| `memo_start_session` / `memo_end_session` | 会话管理 |
| `memo_stats` | 记忆统计 |
| `memo_hot_tags` | 高频特征词 |
| `memo_maintain` | 手动触发生命周期维护 |
| `memo_snapshot` | 全局快照 |

### 人格类（V0.6）
| 工具 | 用途 |
|------|------|
| `persona_ask` | 人格路由问答（3 通道 + 偏离检测） |
| `persona_profile` | 查看人格画像 |

### 待办类（V0.7）
| 工具 | 用途 |
|------|------|
| `todo_add` | 创建待办 |
| `todo_search` | 搜索待办 |
| `todo_list` | 列出待办（支持状态/优先级过滤） |
| `todo_close` | 完成待办（支持批量，完成后自动写记忆） |
| `todo_reopen` | 重新开启已完成待办 |
| `todo_update` | 编辑待办 |
| `todo_check_risk` | 风险检测（逾期/紧急/预警） |

---

## 四、启动与运维

```bash
cd D:\个人\Hanako项目文件\Memo_V0.1.0

# 启动全部服务
start_all.bat

# 停止全部
stop_all.bat

# 看板
http://localhost:9120

# 手动生命周期
python -c "from memo.core.engine import engine; engine.init(); engine.run_lifecycle()"

# 人格基线构建
python -c "from memo.core.engine import engine; engine.init(); engine.build_persona_baseline()"

# 数据库备份：复制 data/memo.db
```

---

## 五、Dashboard 功能

| Tab | 内容 |
|-----|------|
| 图谱视图 | D3.js 力导向特征词图谱（全屏 + 缩放） |
| 列表视图 | 记忆卡片（来源 Agent 标签） |
| 人格画像 | 10 维断言管理（查看/编辑/锁定/删除） |
| 📋 待办 | 独立页面：风险横幅 + 筛选（含数量）+ 完成/重开/取消 |

---

## 六、架构概览

```
┌─────────────────────────────────────────┐
│ MCP Server (18 tools)                   │  ← 任何 Agent 接入
│ memo_*/persona_*/todo_*                 │
├──────────────────┬──────────────────────┤
│ 人格引擎          │ 记忆引擎               │
│ 10维画像·增量更新  │ 检索·门控·CAS·图谱     │
├──────────────────┼──────────────────────┤
│ 待办管理          │ Bridge 导出           │
│ 创建·历史·风险    │ inbox → watcher → 入库 │
├──────────────────┴──────────────────────┤
│ SQLite (memo.db) schema v5              │
│ memory_units · persona_assertions       │
│ todos · todo_history · feature_tags     │
└─────────────────────────────────────────┘
```

---

## 七、Agent 接入

1. **MCP 配置**（必须）：在 Agent 的 `mcp.json` 中配置 memo
2. **Skill 安装**（推荐）：复制 `SKILL.md` 到 Agent 的 skills 目录，让 Agent 自动记录对话
3. **重启 Agent**：断开重连 MCP 连接器

---

## 八、Git

```bash
cd D:\个人\Hanako项目文件\Memo_V0.1.0
git pull origin main   # 拉取最新
git push origin main   # 推送更新
```

---

## 九、相关分析文档

以下两份分析文档已完成审阅（2026-07-15），判断结果见 HANDOFF 补充说明：

1. **`产品改进和优化思路.md`** —— 产品定位与方向判断，整体准确，建议补上待办管理在产品定位中的角色
2. **`项目问题排查结果.md`** —— 技术问题排查，所有 P0 和 P1 问题已修复

---

## 十、已知问题

- JSON 解析正则从贪婪改为非贪婪（`\{.*?\}`），LLM 多段 JSON 输出时不再截断错误
- Dashboard 待办页路由 `/api/todo/action` 必须在 `/api/todo/` 之前匹配

---

## 十一、2026-07-15 修复记录

基于《项目问题排查结果》审阅后执行了以下修复：

| # | 问题 | 严重度 | 修复内容 |
|---|------|:---:|------|
| 1 | `.env` 中 `OPENAI_BASE_URL` 不会被 config.py 读取 | P0 | 改为 `LLM_BASE_URL`（与 config.py 一致） |
| 2 | 数据库默认路径 `memo/data/memo.db` 与实际 `data/memo.db` 不一致 | P0 | 统一为 `data/memo.db`（config.py / .env.example / README / SKILL.md / mcp_config.example.json） |
| 3 | `memo_watcher.py` 的 `_process_inbox()` 中 `agent_name` 使用前未定义 | P0 | 在循环前从第一个文件首条记录提前提取 `agent_name` |
| 4 | `requirements.txt` 缺少 `mcp` 依赖 | P1 | 添加 `mcp>=1.0` |
| 5 | 版本号混乱（HANDOFF V0.7.0 / pyproject 0.1.0 / README V0.6.0） | P1 | 统一为 V0.7.0 |
| 6 | 数据库已备份至 `data/memo.db.backup-20260715` | — | 安全措施 |
