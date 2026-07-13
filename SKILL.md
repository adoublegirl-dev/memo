---
name: memo
description: Memo（麦默）记忆系统——赫布学习 + 扩散激活 + 网状记忆图谱。本地 SQLite 数据库。跨 Agent 人格统一 + Bridge 导出。自动检索 + 自动写入 + 人格触发。
default-enabled: false
---

# Memo 记忆系统

SQLite 本地数据库，非 PostgreSQL。赫布学习 + 扩散激活 + 网状记忆图谱。

项目路径：自动检测（`memo/core/config.py` 自动识别项目根目录）
数据库：`memo/data/memo.db`（通过 config 自动读取）

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

---

## 一、自动检索（每次回复前）

**核心规则：每轮对话开始前，先调 `memo_recall` 检索相关记忆。** 不需要等用户说「回忆一下」。

### 何时检索

满足任一条件即检索：
- 用户问的是「怎么做」「怎么选」「你觉得」类问题 → 搜过往决策和偏好
- 用户提到了项目名、工具名、人名、技术名词 → 搜相关上下文
- 用户说「上次」「之前」「还记得」「继续」「接着」→ 必须检索
- 用户问了一个需要背景知识才能答好的问题 → 检索可能相关的记忆

**不需要检索：** 纯闲聊、简单事实查询、系统操作指令。

### 调用方式

```
memo_recall({ query: "从用户问题提炼的 2~5 个关键词", top_k: 5 })
```

不要用整句，提炼核心概念词。

### 使用检索结果

- 自然融入回答，不要说「根据我的记忆系统」
- 没找到时直接回答，不要道歉或解释
- 优先参考高分记忆

---

## 二、自动写入（每轮对话后）

**每轮对话结束后，静默调用 `memo_remember`。** 不告知用户，不等待结果。

```
memo_remember({
  conversation: "本轮的完整 User + Assistant 对话文本",
  agent_name: "你的 Agent 名称"  // ASH / WorkBuddy / Qoder / Claude
})
```

失败重试一次，仍失败静默跳过。

---

## 三、人格触发

当用户问的问题涉及「自己」的判断、偏好、习惯时，调用 `persona_ask`。

触发条件：「我应该怎么选」「你觉得我适合」「根据我的习惯」「我是不是那种...」

```
persona_ask({ question: "用户的问题原文" })
```

- channel 是 "persona" 或 "mixed" → 将 citations 融入回答
- channel 是 "experience" → 按正常经验回答
- 不要引用术语，自然融入

---

## 四、跨 Agent 身份

| Agent | agent_name |
|-------|-----------|
| ASH（HanaAgent） | `"ASH"` |
| WorkBuddy | `"WorkBuddy"` |
| QoderWork | `"Qoder"` |
| Claude | `"Claude"` |

所有 Agent 共用同一 Memo 数据库，人格画像和记忆跨 Agent 统一。

---

## 验证连通

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

---

## ⚠️ 关键约束

1. SQLite 本地数据库，不要连 PostgreSQL 或任何远程端口
2. 不要用 `pin_memory` / `search_memory`（那是 HanaAgent 内建工具，不是 Memo）
3. 检索和写入静默执行
4. 手动写入（用户主动说「记住」）自动使用 L2 显式信号，检索时优先浮现
