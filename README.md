# Memo（麦默）记忆系统

> V0.6.0 · 赫布学习 + 扩散激活 + 网状记忆图谱 + 人格引擎 + 跨 Agent Bridge

## 一、是什么

Memo 是一个本地运行的 AI 记忆系统，做两件事：

1. **记忆**：用一个 SQLite 文件，记住你在各个 AI Agent 里的每一段对话
2. **人格**：从所有记忆里提炼出你是谁、你怎么想问题、你偏好什么，形成"数字分身"

任何支持 MCP 的 Agent（WorkBuddy / HanaAgent / QoderWork / Claude / Cursor）安装后，共用同一套记忆和人格。

---

## 二、系统要求

- Windows 10+ / macOS 12+
- Python 3.10+
- DeepSeek API Key（或其他 OpenAI 兼容 API）
- 4GB 磁盘空间（含嵌入模型）

---

## 三、安装

### 3.1 解压

将 `Memo_V0.6.0.zip` 解压到任意目录（建议 `D:\Memo` 或 `~/Memo`）。

### 3.2 配置

编辑 `.env` 文件：

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
| **QoderWork** | 设置 → MCP |
| **Claude Desktop** | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| **Cursor** | `.cursor/mcp.json` |

### 4.2 安装 Skill（推荐，让 Agent 自动记录）

将 `SKILL.md` 复制到 Agent 的 skills 目录：

| Agent | 安装目录 |
|-------|---------|
| **WorkBuddy** | `~/.workbuddy/skills/memo/SKILL.md` |
| **HanaAgent** | `~/.hanako/skills/memo/SKILL.md` |
| **QoderWork** | Skills 市场导入 |

安装后 Agent 会在每次对话结束时自动调用 `memo_remember` 写入记忆。

### 4.3 首次建人格基线

```bash
python -c "from memo.core.engine import engine; engine.init(); r=engine.build_persona_baseline(); print(r)"
```

---

## 五、MCP 工具清单（11 个）

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

---

## 六、看板

浏览器打开 `http://localhost:9120`

| Tab | 内容 |
|-----|------|
| 图谱视图 | 特征词 D3 力导向图 |
| 列表视图 | 记忆卡片列表（含来源 Agent 标签） |
| 人格画像 | 10 维度人格断言管理 |

---

## 七、架构

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

## 八、运维

| 操作 | 命令 |
|------|------|
| 启动全部 | `start_all.bat` |
| 停止全部 | `stop_all.bat` |
| 手动生命周期 | `python -c "from memo.core.engine import engine; engine.init(); engine.run_lifecycle()"` |
| 人格增量刷新 | `python -c "from memo.core.engine import engine; engine.init(); engine.update_persona()"` |
| 数据库备份 | 复制 `data/memo.db` |

---

## 九、测试步骤

1. 解压到本地目录，改 `.env` 填 API Key
2. `pip install -r requirements.txt`
3. 初始化：`python -c "from memo.core.engine import engine; engine.init(); print('OK')"`
4. 启动：双击 `start_all.bat`
5. 打开 `http://localhost:9120` 确认看板正常
6. 在 WorkBuddy 的 MCP 配置里添加 memo
7. 重启 WorkBuddy，对话中让它"记住这段对话"
8. 刷新看板，确认记忆数量增长
9. 运行 `build_persona_baseline()` 建人格基线
10. 切换到人格画像 Tab，查看 10 维断言
