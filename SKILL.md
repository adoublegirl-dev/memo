---
name: memo
description: Memo（麦默）记忆系统——赫布学习 + 扩散激活 + 网状记忆图谱。本地 SQLite 数据库。跨 Agent 人格统一 + Bridge 导出。使用场景：用户说「记住xxx」「回忆一下」「之前聊过」。
default-enabled: false
---

# Memo 记忆系统

SQLite 本地数据库，非 PostgreSQL。赫布学习 + 扩散激活 + 网状记忆图谱。

项目路径：自动检测（`memo/core/config.py` 自动识别项目根目录）
数据库：`data/memo.db`（通过 config 自动读取）

## 安装（跨 Agent 统一配置）

任何支持 MCP 的 Agent（HanaAgent / WorkBuddy / QoderWork / Claude / Cursor），在 `mcp.json` 中添加：

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

一键获得 11 个工具：memo_remember / memo_recall / memo_export / persona_ask / persona_profile / ...

## Bridge 导出（跨 Agent 记忆汇入）

Agent 对话结束时调用 `memo_export`：

```
Agent 调 memo_export({ conversation: "完整对话文本", agent_name: "WorkBuddy" })
    ↓
对话写入 ~/.memo/inbox/{timestamp}_WorkBuddy.jsonl
    ↓
Memo watcher 自动检测 → 导入 → 删除原文件
```

启动 watcher：`python scripts/memo_watcher.py`（或包含在 start_all.bat 中）。

### 自动导出规则（最高优先级）

每轮对话结束后，**必须将对话写入 Memo**。可选以下任一方式：

**方式一：memo_remember（推荐，实时入库）**
```
memo_remember({
  conversation: "完整的 User/Assistant 对话文本",
  agent_name: "WorkBuddy"  // 替换为当前 Agent 名称
})
```
适合大多数场景，直接写入数据库，无需额外进程。缺点是每次触发 LLM 门控和提取，多几秒延迟。

**方式二：memo_export（需要 watcher 常驻）**
```
memo_export({ conversation: "完整的 User/Assistant 对话文本", agent_name: "WorkBuddy" })
```
写入 ~/.memo/inbox/ 文件中转，watcher 稍后导入。导出快，但需要 watcher 进程在后台运行。如果 watcher 不在，文件会积压。

触发条件（满足任一即触发）：
- 用户说了一句完整的话，你回复完毕
- 用户说「记住」「记录」「别忘了」
- 用户切换话题或结束对话

不需要告知用户正在写入，静默执行。失败重试一次，仍失败则告知用户。

## 验证连通

首次使用先确认数据库有数据：

```python
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
from memo.integration import MemoClient
c = MemoClient()
s = c.stats()
print(f"会话:{s['sessions']} 记忆:{s['memories']} 特征词:{s['feature_tags']}")
```

记忆数 > 0 即连通成功。

## 写入记忆

当用户说「记住」「记录一下」「帮我存」时：

```python
r = c.remember("用户要记的内容")
print(r["title"] + " | " + str(r["feature_tags"]))
```

写入后告知用户标题和特征词即可，不用废话。

## 检索记忆

当用户说「回忆一下」「之前聊过」「帮我查」「还记得吗」时：

```python
for r in c.recall("查询关键词", top_k=5):
    print(f"[{r['score']:.4f}] {r['title']}")
    print(f"  {r['summary'][:150]}")
```

返回后用自己的话转述给用户。

## 统计

当用户想看记忆概况：

```python
s = c.stats()
print(f"会话:{s['sessions']} 记忆:{s['memories']} 特征词:{s['feature_tags']}")
```

## 关键约束

1. 这是 SQLite 本地文件数据库（`data/memo.db`），不要连 PostgreSQL 或任何远程端口
2. 不要用 `pin_memory` / `search_memory`——那是 HanaAgent 内建工具，不是 Memo
3. 每个 Python 脚本前设置 `HF_ENDPOINT` 环境变量（嵌入模型下载用）
4. 手动写入（用户主动说「记住」）自动使用 L2 显式信号，检索时优先浮现
