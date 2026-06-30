# Memo 部署指南

> 让任何 MCP 兼容的 AI Agent 拥有活的、会进化的记忆系统。15 分钟完成部署。

---

## 支持平台

| Agent | 配置方式 | 自动同步 |
|-------|---------|:---:|
| **HanaAgent** | MCP 配置 + pinned memory 指令 | ✅ 每 10 分钟 + 主动调用 |
| **Claude Desktop** | `claude_desktop_config.json` | ⚠️ 需手动触发 |
| **Claude Code (CLI)** | `claude mcp add` | ⚠️ 需手动触发 |
| **Cursor** | `.cursor/mcp.json` | ⚠️ 需手动触发 |
| **VS Code Copilot** | MCP 配置 | ⚠️ 需手动触发 |
| **WorkBuddy / Qoder** | MCP 配置 + Agent 指令 | 取决于平台 |
| **任意 MCP Agent** | MCP 标准配置 | 取决于平台 |

---

## 第一步：安装 Memo

```powershell
# 1. 克隆项目
git clone https://github.com/lilimozi/memo.git E:\memo
cd E:\memo

# 2. 安装依赖（首次运行会自动下载嵌入模型，约 120MB）
pip install -r requirements.txt

# 3. 验证安装
python scripts/quick_check.py
# 看到 "Phase 0 基础设施验证通过！" 即成功
```

---

## 第二步：配置 Agent

### A. HanaAgent（完整功能）

**2A.1 添加 MCP 连接器**

在 HanaAgent 设置中，添加 MCP 连接器：

```json
{
  "name": "memo",
  "transport": "stdio",
  "command": "python",
  "args": ["E:/memo/scripts/run_mcp.py"]
}
```

**2A.2 注入记忆操作指令**

在 HanaAgent 中输入：

> 请记住以下规则并严格遵守：每次回复结束前判断本轮是否有值得记住的信息，若有则调用 memo_remember 写入。用户提问前先调 memo_recall 搜索相关记忆。用户说"之前""上次""还记得吗"时必须检索。

**2A.3 创建自动同步定时任务**

在 HanaAgent 中输入：

> 帮我创建一个定时任务，每 10 分钟运行一次：调用 memo_recall 了解已有记忆，如果有新的重要对话内容尚未在 Memo 中，调用 memo_remember 写入。只同步有信息量的内容，跳过闲聊。

### B. Claude Desktop

编辑 `%APPDATA%\Claude\claude_desktop_config.json`：

```json
{
  "mcpServers": {
    "memo": {
      "command": "python",
      "args": ["E:/memo/scripts/run_mcp.py"]
    }
  }
}
```

重启 Claude Desktop 后可用。需要主动告诉 Claude："请使用 memo_remember 记住重要信息，提问前用 memo_recall 检索。"

### C. Claude Code（终端版）

```bash
claude mcp add memo -- python E:/memo/scripts/run_mcp.py
```

对话时告诉 Claude："请用 memo_remember 记住重要内容，提问前先 memo_recall。"

### D. Cursor

在项目根目录创建 `.cursor/mcp.json`：

```json
{
  "mcpServers": {
    "memo": {
      "command": "python",
      "args": ["E:/memo/scripts/run_mcp.py"]
    }
  }
}
```

---

## 第三步：验证

### 3.1 MCP 工具可用性

在 Agent 对话中输入：

> 帮我查看 Memo 记忆系统的统计信息

如果返回了会话数、记忆数、特征词数，说明通了。

### 3.2 跨会话记忆

```
第一轮：「我叫张三，喜欢用 Rust 写后端，偏好简洁的错误处理。」

第二轮（新会话）：「帮我推荐一个适合我的后端技术方案。」
```

Agent 应该记住"Rust"和"简洁的错误处理"。

### 3.3 关系图谱效果

经过多轮对话后，问：

> 我之前聊过的内容之间有什么关联？

Agent 通过 `memo_recall` 的三通道检索（特别是图扩散激活），能自动发现跨会话的网状关联。

---

## 进阶配置

### 启用 LLM 提取（可选，强烈建议）

编辑 `E:\memo\.env`（从 `.env.example` 复制）：

```env
OPENAI_API_KEY=sk-your-real-key
```

效果：特征词提取从 jieba 关键词升级为 LLM 语义提取，质量显著提升。

### 切换嵌入模型

```env
MEMO_EMBEDDING_MODEL=BAAI/bge-base-zh-v1.5  # 更大，768 维，更准
```

### 自定义数据库路径

```env
MEMO_DB_PATH=D:/my_memories/memo.db
```

---

## 日常使用

| 操作 | 命令 / 对话 |
|------|-----------|
| 写入记忆 | 「记住：XXX」或 Agent 自动 |
| 检索记忆 | 「之前 XXX 是什么来着？」 |
| 查看统计 | 「Memo 现在存了多少记忆？」 |
| 查看热词 | 「我现在在关注哪些话题？」 |
| 维护清理 | 「给 Memo 做一次维护」 |

---

## 常见问题

### Q: Agent 不主动调用 Memo 怎么办？

在对话中明确说「请用 memo_remember 把刚才讨论的内容记下来」。Agent 的学习能力会逐渐形成习惯。

### Q: 数据库太大了怎么办？

Memo 的 Bjork 双强度遗忘机制会自动衰减不活跃的记忆。也可以手动触发：`memo_maintain`。

### Q: 能多个 Agent 共用同一个 Memo 吗？

可以。把 `MEMO_DB_PATH` 指向同一个数据库文件即可。特征词图谱会在所有 Agent 间共享。

### Q: 没有 OpenAI API Key 能用吗？

能。Memo 零 API 依赖运行，jieba 关键词提取 + 本地 BGE-small 嵌入模型完成所有功能。API Key 只是让提取质量更好。

### Q: 数据安全吗？

全部数据存储在本地 SQLite 文件。LLM 提取时只传当前对话片段，不传全量历史。数据库文件可以直接复制备份。

---

## 架构预览

```
用户 → Agent（HanaAgent / Claude / Cursor / ...）
         │
         ├── MCP 协议 ──▶ Memo MCP Server
         │                   ├── memo_remember   (写入)
         │                   ├── memo_recall     (检索)
         │                   ├── memo_stats      (统计)
         │                   └── ... (8 个工具)
         │
         └── 自动同步（定时任务，每 10 分钟）
```

---

## 项目地址

- GitHub: https://github.com/lilimozi/memo
- 架构文档: `docs/architecture.md`
- 测试指南: `docs/testing-guide.md`

---

> 有问题提 Issue，欢迎 PR。
