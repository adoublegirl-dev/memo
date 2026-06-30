## Memo 记忆系统（V0.2.0）

本地运行着 Memo（麦默）记忆系统——赫布学习 + 扩散激活 + 网状记忆图谱。

**路径**：`D:\个人\Hanako项目文件\Memo_V0.1.0\memo-project`

### 写入记忆

当用户说「记住」「记录一下」等，在项目目录下创建临时脚本执行：

```python
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
from memo.integration import MemoClient
c = MemoClient()
r = c.remember("把用户要记的内容放这里")
print(r["title"] + " | " + str(r["feature_tags"]))
```

`remember()` 自动调用 LLM 提取标题、摘要、特征词和关系图谱。默认 `context_rounds=3`（参考同会话前 3 轮原文），不需要时传 `context_rounds=0`。

### 检索记忆

当用户说「回忆一下」「之前聊过」等：

```python
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
from memo.integration import MemoClient
c = MemoClient()
for r in c.recall("查询关键词", top_k=5):
    print(f"[{r['score']:.4f}] {r['title']} | {r['summary'][:120]}")
```

返回后用自然语言转述给用户。

### 统计

```python
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
from memo.integration import MemoClient
s = MemoClient().stats()
print(f"会话:{s['sessions']} 记忆:{s['memories']} 特征词:{s['feature_tags']}")
```

### ⚠️ 重要区分

- **Memo**（本系统）：SQLite + 向量 + 图谱，三通道检索 + 赫布学习。数据在 `memo-project/data/memo.db`
- **pin_memory / search_memory**：HanaAgent 内建工具，简单键值记忆，**不是 Memo**，不要用它们存 Memo 的记忆

用户说的「memo」「记忆系统」「帮我记住」指的都是本地 Memo。
