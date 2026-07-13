## Memo 记忆系统（SQLite 本地数据库，非 PostgreSQL）

本地运行着 Memo（麦默）记忆系统——赫布学习 + 扩散激活 + 网状记忆图谱。
数据库：SQLite 文件，不是 PostgreSQL，不用连任何端口。

### 验证是否连通

先执行这一步确认数据库有数据：

```python
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
from memo.integration import MemoClient
c = MemoClient()
s = c.stats()
print(f"会话:{s['sessions']} 记忆:{s['memories']} 特征词:{s['feature_tags']}")
```

如果返回记忆数 > 0，说明连通成功，可以进行后续操作。

### 写入记忆

当用户说「记住」「记录一下」「帮我存」时：

```python
r = c.remember("用户要记的内容")
print(r["title"] + " | " + str(r["feature_tags"]))
```

### 检索记忆

当用户说「回忆一下」「之前聊过」「帮我查」时：

```python
for r in c.recall("查询关键词", top_k=5):
    print(f"[{r['score']:.4f}] {r['title']} | {r['summary'][:120]}")
```

### ⚠️ 关键约束

1. 这是 SQLite 本地文件数据库，不要连 PostgreSQL 或任何远程端口
2. 不要用 pin_memory / search_memory（那是 HanaAgent 内建工具，不是 Memo）
3. 数据库路径是 data/memo.db，通过 config 读取，不需要手动指定
4. 执行 Python 脚本前先 cd 到项目目录
