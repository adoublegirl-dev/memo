## Memo 记忆系统

本地运行着 Memo（麦默）记忆系统——赫布学习 + 扩散激活 + 网状记忆图谱。

**路径**：`D:\个人\Hanako项目文件\Memo_V0.1.0\memo-project`

**使用方式**：通过 Python 脚本调用 engine API。每次写入/检索时，创建一个临时脚本执行。

### 写入记忆

当用户说「记住」「记录一下」「帮我存一下」等，执行：

```bash
powershell -Command "$env:HF_ENDPOINT='https://hf-mirror.com'; cd 'D:\个人\Hanako项目文件\Memo_V0.1.0\memo-project'; python -c 'import sys,os; sys.path.insert(0,\".\"); from memo.core.engine import engine; engine.init(); s=engine.start_session(title=\"会话标题\"); r=engine.remember_conversation(session_id=s.id, conversation=\"\"\"用户说的原文或对话片段\"\"\", context_rounds=3); print(r[\"title\"])'"
```

`remember_conversation` 会自动调用 LLM 提取标题、摘要、特征词和关系图谱。`context_rounds=3` 会让 LLM 参考同会话前 3 轮原文，判断是否有补充信息纳入摘要。

如果不需要上下文感知，设 `context_rounds=0`。

写入后告知用户：标题 + 特征词即可。

### 检索记忆

当用户说「回忆一下」「之前聊过」「帮我查查」等，执行：

```bash
powershell -Command "$env:HF_ENDPOINT='https://hf-mirror.com'; cd 'D:\个人\Hanako项目文件\Memo_V0.1.0\memo-project'; python -c 'import sys,os; sys.path.insert(0,\".\"); from memo.core.engine import engine; engine.init(); res=engine.recall(\"查询关键词\", top_k=5); [print(f\"[{r[\"\"\"score\"\"\"]:.4f}] {r[\"\"\"title\"\"\"]}\\n  {r[\"\"\"summary\"\"\"][:150]}\") for r in res]'"
```

返回结果后，用自然语言转述给用户。

### 统计

用户想看记忆概况时：

```bash
powershell -Command "$env:HF_ENDPOINT='https://hf-mirror.com'; cd 'D:\个人\Hanako项目文件\Memo_V0.1.0\memo-project'; python -c 'import sys,os; sys.path.insert(0,\".\"); from memo.core.engine import engine; engine.init(); s=engine.stats(); print(f\"会话:{s[\"\"\"sessions\"\"\"]} 记忆:{s[\"\"\"memories\"\"\"]} 特征词:{s[\"\"\"feature_tags\"\"\"]} TOP:{s[\"\"\"top_tags\"\"\"][:10]}\")'"
```

### ⚠️ 重要区分

- **Memo**（本系统）：SQLite + 向量 + 图谱，支持三通道检索和赫布学习。数据在 `memo-project/data/memo.db`
- **pin_memory / search_memory**：HanaAgent 内建工具，简单的键值记忆，**不是 Memo**，不要用它们来存 Memo 记忆

用户说的「memo」「记忆系统」「帮我记住」指的都是本地的 Memo 系统。不要混淆为 pin_memory 或远程服务器。
