---
name: memo
description: Memo（麦默）记忆系统——赫布学习 + 扩散激活 + 网状记忆图谱。本地 SQLite 数据库。让 Agent 能长期记住用户信息并在对话中检索调用。使用场景：用户说「记住xxx」「回忆一下」「之前聊过」。
default-enabled: false
---

# Memo 记忆系统

SQLite 本地数据库，非 PostgreSQL。赫布学习 + 扩散激活 + 网状记忆图谱。

项目路径：`D:\个人\Hanako项目文件\Memo_V0.1.0`
数据库：`data/memo.db`（通过 config 自动读取）

## 验证连通

首次使用先确认数据库有数据：

```python
import sys, os
sys.path.insert(0, r"D:\个人\Hanako项目文件\Memo_V0.1.0")
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
