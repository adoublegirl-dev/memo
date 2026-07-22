# Memo（麦默）记忆系统

> V0.9-alpha · 记忆 + 人格 + 待办 + Context Space + 跨 Agent Bridge

## 一、是什么

Memo 是一个本地运行的 AI Context Space，做四件事：

1. **记忆**：用一个 SQLite 文件，沉淀各个 AI Agent 里的长期上下文
2. **空间**：用 Context Space 按项目、事项、客户、产品线组织记忆、待办和会话
3. **人格**：从所有记忆里提炼出你是谁、你怎么想问题、你偏好什么，形成"数字分身"
4. **行动**：把记忆中的下一步沉淀为待办、风险和项目推进线索

任何支持 MCP 的 Agent（WorkBuddy / HanaAgent / QoderWork / Claude / Cursor）安装后，共用同一套记忆、空间、人格和待办。

V0.9 后续记忆地基改造方案见：[`docs/V0.9-episode-memory-and-agent-import-plan.md`](docs/V0.9-episode-memory-and-agent-import-plan.md)。该方案覆盖 episode-level canonical memory、新老用户迁移、历史 Agent 会话导入和主流 Agent 兼容策略。

---

## 二、系统要求

- Windows 10+ / macOS 12+
- Python 3.10+
- DeepSeek API Key（或其他 OpenAI 兼容 API）
- 4GB 磁盘空间（含嵌入模型）

---

## 三、安装

如果安装对象是不熟悉命令行的同事，Windows 下推荐直接双击全量安装器/升级器：

```text
full_install.bat
```

它会自动判断新装、升级或修复：已有的 `.env`、`data/` 不会覆盖；缺少的依赖会补齐；MCP 只更新 memo 这一项。

安装过程中会先检查 `.env` 是否已有 `LLM_API_KEY`：已有则跳过；没有则提供 DeepSeek / OpenAI / 自定义 OpenAI-compatible 模型选择、Key 输入和连接测试。默认推荐 `deepseek-v4-flash`，其次可选 `deepseek-v4-pro`；记忆写入、总结和治理会持续消耗 token，普通用户建议优先使用便宜模型。用户也可以跳过，之后手动编辑 `.env` 配置。安装完成后，终端会提示到对应 Agent 中配置并启用 MCP，并给出 `install_output/` 下可复制的 ready-to-paste 配置文件。

旧版一键安装器仍可使用：

```text
install.bat
```

如果只是想检查环境，不做写入：

```bash
python scripts/install_doctor.py
python scripts/install_doctor.py --json
```

下面是开发者/手动安装流程。

### 3.1 解压

将 `Memo_V0.7.0.zip` 解压到任意目录（建议 `D:\Memo` 或 `~/Memo`）。

### 3.2 配置

如果你跳过了安装器里的 Key 配置，也可以稍后手动编辑 `.env` 文件：

```
LLM_API_KEY=sk-your-deepseek-key
LLM_BASE_URL=https://api.deepseek.com/v1
MEMO_DB_PATH=data/memo.db
```

如果用自己的 API，改 `LLM_BASE_URL` 和模型名即可。

### 3.3 安装依赖

```bash
pip install -r requirements.txt
```

首次运行时会自动下载嵌入模型（`BAAI/bge-small-zh-v1.5`，约 100MB），需要联网。国内用户设置镜像：

```bash
set HF_ENDPOINT=https://hf-mirror.com
```

### 3.4 初始化数据库

```bash
python -c "from memo.core.engine import engine; engine.init(); print('OK')"
```

### 3.5 启动服务

```bash
start_all.bat        # Windows
# 或
python scripts/memo_dashboard.py   # 看板 (http://localhost:9120)
python scripts/memo_watcher.py     # 守护进程（Bridge inbox 监控 + 人格刷新）
```

### 3.6 启动桌面助手（实验性）

Memo Desktop Companion 是 Electron 桌面常驻入口，用于待办提醒、项目候选提醒和快速打开 Memo。

```bash
npm install
npm run desktop:dev
```

Windows 也可以直接双击：

```text
desktop.bat
```

首次给其他用户安装桌面助手时，可运行：

```text
desktop_install.bat
```

桌面助手现在同时承担 Memo Launcher 职责：启动后会检测 Memo 后端服务；如服务未启动，会尝试拉起 `start_all.bat`，也可在窗口里手动启动、停止、重启服务。

如需生成 Windows 桌面软件：

```bash
npm run desktop:pack   # 生成免安装目录，用于本地检查
npm run desktop:dist   # 生成 Windows 安装包 / portable exe
```

建议先启动 Memo 服务，再启动桌面助手。

---

## 四、接入 Agent

### 4.1 安装 MCP（必须）

在 Agent 的 MCP 配置文件中添加：

```json
{
  "mcpServers": {
    "memo": {
      "command": "python",
      "args": ["<项目路径>/scripts/run_mcp.py"]
    }
  }
}
```

> 将 `<项目路径>` 替换为 Memo 解压目录的绝对路径（如 `D:/Memo` 或 `~/Memo`）。

| Agent | 配置文件路径 |
|-------|-------------|
| **WorkBuddy** | `~/.workbuddy/mcp.json` |
| **HanaAgent** | 设置 → MCP 连接器 |
| **QoderWork** | 设置 → MCP；也可用 `install_output/qoder_mcp_ready_to_paste.json` 手动导入 |
| **Claude Desktop** | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| **Cursor** | `.cursor/mcp.json` |

### 4.2 安装 Skill（推荐，让 Agent 自动运行）

将 `SKILL.md` 复制到 Agent 的 skills 目录：

| Agent | 安装目录 |
|-------|---------|
| **WorkBuddy** | `~/.workbuddy/skills/memo/SKILL.md` |
| **HanaAgent** | `~/.hanako/skills/memo/SKILL.md` |
| **QoderWork** | Skills 市场导入；若本地存在 `~/.qoder` / `~/.qoderwork`，安装器会尝试复制到对应 skills 目录 |

安装后 Agent 会：
- **每轮对话前**自动检索相关记忆
- **每轮对话后**静默写入对话记忆
- **涉及决策/偏好时**自动调用人格引擎

### 4.3 注入 Agent 提示词

将 `AGENT_PROMPT.md` 的内容追加到 Agent 的 System Prompt 中，Agent 就会自动执行检索+记忆+人格三阶段联动。

### 4.4 首次建人格基线

```bash
python -c "from memo.core.engine import engine; engine.init(); r=engine.build_persona_baseline(); print(r)"
```

---

## 五、Agent 行为（接入后自动执行）

| 阶段 | 时机 | 工具 | 说明 |
|------|------|------|------|
| **检索** | 每次回复前 | `memo_recall` | 自动提炼关键词检索过往记忆，融入回答 |
| **写入** | 每次回复后 | `memo_remember` | 静默写入本轮对话，不打扰用户 |
| **人格** | 决策/偏好类问题 | `persona_ask` | 匹配人格画像，给出带立场的回复 |

---

## 六、MCP 工具清单（核心工具）

| 工具 | 用途 | 示例 |
|------|------|------|
| `memo_remember` | 写入记忆 | `memo_remember({conversation:"...", agent_name:"WorkBuddy"})` |
| `memo_recall` | 检索记忆 | `memo_recall({query:"数据治理规则"})` |
| `memo_export` | Bridge 导出（文件中转） | `memo_export({conversation:"...", agent_name:"Qoder"})` |
| `memo_start_session` | 开始记忆会话 | |
| `memo_end_session` | 结束记忆会话 | |
| `memo_stats` | 查看统计 | |
| `memo_hot_tags` | 高频特征词 | |
| `memo_maintain` | 生命周期维护 | |
| `memo_snapshot` | 全局快照 | |
| `persona_ask` | 人格路由问答 | `persona_ask({question:"我应该怎么推进这个项目？"})` |
| `persona_profile` | 查看人格画像 | `persona_profile({dimension:"value"})` |
| `todo_add` | 创建待办 | `todo_add({title:"写完报告",priority:"high",due_date:"2026-07-20"})` |
| `todo_list` | 列出待办 | `todo_list({status:"todo+doing"})` |
| `todo_close` | 完成待办 | `todo_close({ids:["abc123"]})` |
| `todo_check_risk` | 风险检测 | 返回逾期/紧急/预警 |
| `space_create` | 创建 Context Space | `space_create({name:"Memo"})` |
| `space_list` | 列出 Space | |
| `space_activate` / `space_deactivate` | 激活/退出当前 Space | |
| `space_profile` | 查看 Space 简报 | |
| `space_recall` | 在 Space 内检索 | |
| `space_detect` | 检测文本可能属于哪个 Space | |
| `memory_govern` | 记忆治理：标重要/错误/过期/静默/软删除 | |

---

## 七、看板

浏览器打开 `http://localhost:9120`

| Tab | 内容 |
|-----|------|
| 总览 | 记忆、会话、关系、待办和活跃特征词 |
| 记忆治理 | 搜索记忆，标重要/错误/过期/静默/软删除 |
| 上下文空间 | Space 创建、编辑、归档、简报、记忆解绑 |
| 待办 | 创建、完成、重开待办，支持绑定 Space |
| 人格画像 | 10 维度人格断言管理 |
| 图谱视图 | 当前为入口占位，下一阶段接入 Canvas 图谱 |

---

## 八、架构

```
┌─────────────────────────────────────────┐
│ MCP Server (11 tools)                   │  ← 任何 Agent 接入
│ memo_remember / recall / export / ...   │
├─────────────────────────────────────────┤
│ 人格路由器 (Persona Router)              │  ← 领域匹配 → 人格/混合/经验通道
├──────────────────┬──────────────────────┤
│ 人格引擎          │ 记忆引擎               │
│ 10维画像·增量更新  │ 检索·门控·CAS·图谱     │
├──────────────────┴──────────────────────┤
│ SQLite (memo.db)                        │
│ memory_units · persona_assertions · ... │
└─────────────────────────────────────────┘
```

---

## 九、运维

| 操作 | 命令 |
|------|------|
| 启动全部 | `start_all.bat` |
| 停止全部 | `stop_all.bat` |
| 手动生命周期 | `python -c "from memo.core.engine import engine; engine.init(); engine.run_lifecycle()"` |
| 人格增量刷新 | `python -c "from memo.core.engine import engine; engine.init(); engine.update_persona()"` |
| 数据库备份 | 复制 `data/memo.db` |
| 安全升级 | `upgrade.bat` 或先 `python scripts/init_db.py` 再 `start_all.bat` |
| 环境自检 | `python scripts/doctor.py` |
| 安全打包 | `python scripts/build_release.py --include-dist` |

---

## 十、测试步骤

1. 解压到本地目录，改 `.env` 填 API Key
2. `pip install -r requirements.txt`
3. 初始化：`python -c "from memo.core.engine import engine; engine.init(); print('OK')"`
4. 启动：双击 `start_all.bat`
5. 打开 `http://localhost:9120` 确认看板正常
6. 在 Agent 的 MCP 配置里添加 memo
7. 重启 Agent，对话中让它"记住这段对话"
8. 刷新看板，确认记忆数量增长
9. 运行 `build_persona_baseline()` 建人格基线
10. 切换到人格画像 Tab，查看 10 维断言
