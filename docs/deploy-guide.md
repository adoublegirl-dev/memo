# Memo 部署指南

> 让任何 MCP 兼容的 AI Agent 拥有活的、会进化的记忆系统。赫布学习 + 扩散激活 + 网状记忆图谱 + 人格引擎。

---

## 支持平台

| Agent | 配置方式 |
|-------|---------|
| **HanaAgent** | MCP 配置 + Agent 提示词 |
| **Claude Desktop** | `claude_desktop_config.json` |
| **Claude Code (CLI)** | `claude mcp add` |
| **Cursor** | `.cursor/mcp.json` |
| **任意 MCP Agent** | MCP 标准配置 |

---

## 第一步：Clone + 安装

```bash
git clone https://github.com/adoublegirl-dev/memo.git <项目路径>
cd <项目路径>

pip install -r requirements.txt
pip install "mcp>=1.0"
```

> pip 慢加镜像：`pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple`

> 将 `<项目路径>` 替换为你的 Memo 实际目录。

---

## 第二步：配置环境

```bash
copy .env.example .env
# 编辑 .env 填入你的 API Key
```

填入（DeepSeek 示例）：

```env
LLM_API_KEY=sk-your-key
LLM_BASE_URL=https://api.deepseek.com/v1
MEMO_EXTRACTION_MODEL=deepseek-v4-flash
MEMO_GATING_MODEL=deepseek-v4-flash
MEMO_DB_PATH=data/memo.db
MEMO_LOG_LEVEL=INFO
```

> 无 API Key 也能跑（jieba 降级提取），只是摘要质量稍低。

---

## 第三步：初始化 + 自检

```bash
# 国内用户先设镜像
# Windows: set HF_ENDPOINT=https://hf-mirror.com
# macOS/Linux: export HF_ENDPOINT=https://hf-mirror.com

python scripts/init_db.py
```

看到「自检通过！Memo 系统就绪。」即成功。

---

## 第四步：配置 Agent 接入

### HanaAgent MCP 配置

```json
{
  "mcpServers": {
    "memo": {
      "command": "python",
      "args": ["<项目路径>/scripts/run_mcp.py"],
      "env": { "HF_ENDPOINT": "https://hf-mirror.com" }
    }
  }
}
```

### 注入 Agent 提示词

复制 `AGENT_PROMPT.md`（或见下文快速版本）到助手的 System Prompt 中：

```
## Memo 记忆系统

写入记忆时，执行 Python 脚本：
import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
from memo.integration import MemoClient
c = MemoClient()
r = c.remember("用户要记的内容")
print(r["title"] + " | " + str(r["feature_tags"]))

检索记忆：
c.recall("查询关键词", top_k=5)

每次写入后告知用户标题+特征词即可。不要用 pin_memory。
```

---

## 第五步：启动服务

双击 `start_all.bat`（Windows），或运行：

```bash
python scripts/memo_dashboard.py   # 看板 → http://localhost:9120
python scripts/memo_watcher.py     # 后台守护进程
```

停止：双击 `stop_all.bat`

---

## 第六步：导入历史会话（可选）

如果想把 HanaAgent 过往的聊天记录一次性入库：

### 6.1 导入前准备

```bash
# 确保服务已停止
double-click stop_all.bat  # Windows

# （可选）清空现有测试数据
python scripts/_mark_legacy.py
python scripts/_clean_legacy.py
```

### 6.2 执行导入

```bash
# Windows: set HF_ENDPOINT=https://hf-mirror.com
python scripts/import_sessions.py --skip-cas
```

- `--skip-cas`：跳过逐条变更检测，速度快 3-4 倍
- 脚本自动扫描 `~/.hanako/agents/hanako/sessions/` 下所有历史会话
- 每轮对话：MVG 门控预判价值 → LLM 提取特征词/摘要 → 写入
- 门控自动过滤闲聊（"嗯好的"、"知道了"等），只保留有价值内容

### 6.3 导入后处理

导入时跳过了 CAS 变更检测，需要导入后统一做一次批量扫描：

```bash
python -c "from memo.core.engine import engine; engine.init(); r=engine.run_lifecycle(); print(r)"
```

这会执行：遗忘衰减 → consolidation → CAS 批量变更扫描 → 快照。

> 批量扫描比逐条对比高效得多——导入 77 轮只需几十秒，而逐条需要数百次额外 LLM 调用。

### 6.4 验证导入结果

```bash
# 启动看板，浏览器打开 http://localhost:9120
# 切换到「图谱视图」查看特征词关联网络
```

---

## 日常操作速查

| 操作 | 命令 |
|------|------|
| 一键启动 | 双击 `start_all.bat` |
| 一键停止 | 双击 `stop_all.bat` |
| 查看看板 | `http://localhost:9120` |
| 导入历史会话 | `python scripts/import_sessions.py --skip-cas` |
| 导入后批量 CAS 扫描 | `python -c "from memo.core.engine import engine; engine.init(); engine.run_lifecycle()"` |
| 标记现有数据 | `python scripts/_mark_legacy.py` |
| 清理标记数据 | `python scripts/_clean_legacy.py` |
| 更新代码 | `git pull` |

---

## 核心能力

### MVG 记忆价值门控
写入前 LLM 4 维评分预判，总分 < 3.0 跳过（过滤闲聊）

### CAS 变更感知
写入后自动检测是否推翻旧事实，标记旧记忆失效

### SCB 会话凝聚力加成
同会话内特征词关联边权重加成 + 赫布学习

### D3.js 力导向图
看板「图谱视图」可视化特征词节点 + 赫布关系边，点击节点高亮邻居 + 关联记忆

### 人格引擎（10 维度）
从记忆自动提炼 values / decisions / preferences / identity / sensitivity / relationship / knowledge / communication / mental_model / emotion

---

## 配置项速查

| 环境变量 | 默认值 | 说明 |
|------|------|------|
| `LLM_API_KEY` | — | LLM API Key |
| `LLM_BASE_URL` | `https://api.deepseek.com/v1` | API 地址 |
| `MEMO_EXTRACTION_MODEL` | `deepseek-v4-flash` | 提取用模型 |
| `MEMO_GATING_MODEL` | `deepseek-v4-flash` | 门控用模型 |
| `MEMO_DB_PATH` | `data/memo.db` | 数据库路径 |
| `MEMO_GATING_ENABLED` | `true` | 启用门控 |
| `MEMO_GATING_THRESHOLD` | `3.0` | 门控写入阈值 |
| `MEMO_CHANGE_DETECTION_ENABLED` | `true` | 启用 CAS |
| `MEMO_SESSION_BOOST_ALPHA` | `0.5` | 会话加成系数 |
| `MEMO_SESSION_SPREAD_BOOST` | `1.2` | 扩散加成系数 |

---

## 项目结构

```
项目根目录/
├── memo/               # 核心 Python 包
│   ├── core/           # 引擎 + 配置
│   ├── store/          # 数据库/图/向量
│   ├── models/         # 数据模型
│   ├── extraction/     # LLM 提取器 + 门控 + 变更检测
│   ├── retrieval/      # 三通道检索 + 融合
│   ├── lifecycle/      # 遗忘/固化/快照
│   ├── persona/        # 人格引擎
│   ├── mcp/            # MCP Server
│   ├── integration/    # MemoClient 直接调用
│   └── utils/          # LLM/嵌入/日志
├── scripts/            # 运维脚本
├── docs/               # 文档
├── data/               # 数据库文件
├── start_all.bat       # 一键启动
├── stop_all.bat        # 一键停止
└── .env.example        # 配置模板
```

---

## 常见问题

### Q: 数据库被锁了怎么办？

先停止服务，然后用 SQLite 工具检查数据库完整性。切勿直接删除 `memo.db` 文件。如需重建，先备份：`copy memo\data\memo.db memo\data\memo.db.backup`，再运行 `python scripts/init_db.py` 重建空库。

### Q: LLM 调用失败？

已内置 3 次指数退避重试。仍失败会自动降级到 jieba 提取，不丢数据。导入大数量时加 `--skip-cas` 跳过变更检测，导入后统一跑 `run_lifecycle()`。

### Q: 怎么清理测试数据？

先跑 `python scripts/_mark_legacy.py` 标记现有数据，等正式数据入库后跑 `python scripts/_clean_legacy.py` 清标记数据。

### Q: 数据安全吗？

全部存储在本地 SQLite 文件。LLM 提取只传当前对话片段，不传全量历史。

---

> GitHub: https://github.com/adoublegirl-dev/memo
