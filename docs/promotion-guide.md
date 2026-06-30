# Memo 推广指南

> 给你的 Agent 装上它会呼吸的记忆。15 分钟，一行配置，永远告别"上一轮我们聊到哪了"。

---

## 一句话说清楚

**Memo 是一个开源的 Agent 记忆层。** 它让 Claude、Cursor、HanaAgent、WorkBuddy 等任何 MCP 兼容 Agent，拥有跨会话、会自动关联、会自动遗忘的持久记忆。不需要微调模型，不需要云服务，一个 SQLite 文件搞定。

---

## 为什么你的 Agent 需要它

> "Agent 忘了上周跟你聊过的项目细节？忘了你的偏好？每次新会话都像第一次见面？"

这不是 Agent 的问题，是它没有**独立于上下文窗口的记忆系统**。上下文窗口是 RAM，关机就没了。Memo 是硬盘——而且是会自己整理文件夹的硬盘。

| 没有 Memo | 有 Memo |
|-----------|---------|
| 每次对话从零开始 | Agent 自动检索相关历史 |
| 翻聊天记录靠手工搜索 | 三通道混合检索（语义+关键词+关系图） |
| 记忆片段孤立，无关联 | 特征词图谱自动发现跨会话的网状关联 |
| 什么都不忘，记忆变垃圾场 | Bjork 双强度遗忘，重要的留、不重要的自然衰减 |
| 换 Agent 换记忆格式 | 任何 MCP Agent 共享同一个记忆库 |

---

## 核心能力

### 1. 三层记忆架构

```
L0 热记忆体 → 高频词 + 近期摘要，常驻上下文，<10ms
L1 温记忆体 → 特征关系图谱 + 赫布权重进化，100ms
L2 冷存储   → 完整对话原文 + 双时序历史，按需检索
```

### 2. 网状记忆图谱（独家）

不是把你说的关键词存成标签，而是让特征词之间自动建立带权重的有向边。同一次对话中共同出现的特征词，边权重自动增长。跨会话扩散激活：搜"A"的时候，系统沿边走到"B""C""D"，把散落在不同会话的关联记忆全捞出来。

```
搜"排位赛" → 找到排位赛的记忆
            → 同时发现"ELO算法"与排位赛有强关联（边权重 0.87）
            → 自动关联到三周前聊过的"ELO 匹配方案"记忆
            → 再沿边扩散到"天梯赛"...
```

### 3. 三通道混合检索

- **通道①** 向量语义：用本地 BGE-small 模型编码查询，cosine 相似度搜索
- **通道②** BM25 全文：SQLite FTS5 全文索引，关键词精准匹配
- **通道③** 图扩散激活：从命中特征词出发，沿赫布边 BFS 游走，发现间接关联

三通道结果用 RRF（Reciprocal Rank Fusion）融合排序。

### 4. 会遗忘才是好记忆

不像大多数系统那样"要么全记要么手动删"。Memo 用神经科学里的 **Bjork 双强度遗忘模型**：

- **存储强度**（storage_strength）：只增不减，表征"这个信息有多重要"
- **检索强度**（retrieval_strength）：不用时每天衰减 2%，表征"现在还能多快想起它"

很久没提但很重要的事，系统知道它还在，只是暂时不活跃。真正无用的信息自然沉底。不删数据，不丢记忆，不污染检索结果。

### 5. 双时序事实追踪

"3 月时我在 A 公司"→"6 月我跳槽去了 B 公司"

普通系统会同时返回两条矛盾信息。Memo 用双时序（valid_from/valid_until）追踪事实的时间窗口，新事实自动标记旧事实为"已被替代"。问"现在在哪工作"只返回 B 公司，问"3 月时在哪工作"能正确返回 A 公司。

---

## 与主流方案的对比

| | Memo | Mem0 | Hermes 内置记忆 | Claude 原生记忆 |
|---|---|---|---|---|
| 赫布学习图谱 | ✅ | ⚠️ 实体层 | ❌ | ❌ |
| 扩散激活检索 | ✅ | ❌ | ❌ | ❌ |
| 双强度遗忘 | ✅ | ❌ | ❌（硬截断） | ❌ |
| 双时序事实 | ✅ | ❌ | ❌ | ❌ |
| MCP 通用 | ✅ | ✅ | ❌（绑定 Hermes） | ❌（绑定 Claude） |
| 零 API 可运行 | ✅ | ❌ | 部分 | ❌ |
| 开源 | MIT | Apache 2.0 | MIT | 闭源 |
| 本地运行 | ✅ SQLite | ⚠️ 需要服务 | ✅ | ❌ |

---

## 快速开始（给新用户的三步）

### 第一步：克隆安装

```bash
git clone https://github.com/adoublegirl-dev/memo.git
cd memo/memo-project
pip install -r requirements.txt
python scripts/quick_check.py   # 看到 "Phase 0 验证通过" 即成功
```

首次运行会自动下载 BGE-small 嵌入模型（约 120 MB），之后离线可用。

### 第二步：配到你的 Agent

无论用什么 Agent，只要支持 MCP 协议，加这段配置：

```json
{
  "mcpServers": {
    "memo": {
      "command": "python",
      "args": ["你的路径/memo/scripts/run_mcp.py"]
    }
  }
}
```

| Agent | 配置文件位置 |
|-------|------------|
| Claude Desktop | `%APPDATA%\Claude\claude_desktop_config.json` |
| Cursor | 项目根目录 `.cursor/mcp.json` |
| Claude Code | `claude mcp add memo -- python ...` |
| HanaAgent | 设置 → MCP → 添加连接器 |
| 其他 | 各自 MCP 配置处 |

### 第三步：验证

对你的 Agent 说：

> 帮我查看 Memo 记忆统计

返回了会话数、记忆数、特征词数，就通了。之后 Agent 会自动用 `memo_remember` 记重要内容，用 `memo_recall` 检索历史。

**可选的 LLM 增强：** 复制 `.env.example` 为 `.env`，填 `OPENAI_API_KEY`，特征词提取从 jieba 关键词升级为 LLM 语义提取。

---

## 8 个 MCP 工具一览

| 工具 | 功能 |
|------|------|
| `memo_remember` | 写入记忆（自动提取特征词/摘要/关系） |
| `memo_recall` | 三通道混合检索 |
| `memo_start_session` | 开始新会话 |
| `memo_end_session` | 结束会话 |
| `memo_stats` | 统计：会话数、记忆数、特征词、关系 |
| `memo_hot_tags` | 当前高频特征词（你的 Agent 在关注什么） |
| `memo_maintain` | 手动触发生命周期维护 |
| `memo_snapshot` | 全局记忆快照（Agent 对你的认知画像） |

---

## 进阶：自动同步

让 Agent 主动调用是第一步。要实现"每条对话自动记"，两种做法：

**方式一（推荐）：Agent 指令**
在 Agent 的 System Prompt 中加一行：
> 每轮回复结束前，判断是否有值得记住的信息，若有则调用 memo_remember

**方式二：定时自动化**
HanaAgent 支持创建定时任务（每 N 分钟），后台 Agent 自动扫描新对话并写入 Memo。

---

## 数据安全

- 所有数据存储在本地 SQLite 文件（一个文件，随时复制备份）
- 无云服务、无遥测、无第三方数据传输
- LLM 提取时只传当前对话片段（不传全量历史）
- 零 API Key 可运行（jieba 关键词 + 本地嵌入模型）

---

## 技术栈

| 组件 | 选择 |
|------|------|
| 语言 | Python 3.11+ |
| 数据库 | SQLite + FTS5 全文索引 |
| 嵌入模型 | BGE-small-zh-v1.5（512 维，本地运行） |
| 图计算 | 自建邻接表（1-10 万节点无需 Neo4j） |
| 对外协议 | MCP stdio |
| LLM 提取（可选） | GPT-4o-mini / 任何 OpenAI 兼容 API |
| 许可证 | MIT |

---

## 常见问题

**Q: 我能让多个 Agent 共用同一个记忆库吗？**  
A: 可以。把所有 Agent 的 MCP 配置指向同一个数据库路径即可。特征词图谱会在所有 Agent 间共享。

**Q: 没有 OpenAI API Key 能用吗？**  
A: 能。Memo 零 API 依赖运行。API Key 只是让特征词提取更精准。

**Q: 数据库会无限膨胀吗？**  
A: 不会。Bjork 双强度遗忘机制自动衰减不活跃记忆。1 万次对话大约 100 MB。

**Q: 支持英文吗？**  
A: BGE-small 中英文都支持。切换到 BGE-base-en-v1.5 可优化英文场景。

**Q: 能迁移到 Neo4j 吗？**  
A: 架构预留了图数据库接口。数据量突破 SQLite 边界时可平滑迁移。

---

## 项目地址

- GitHub: https://github.com/adoublegirl-dev/memo
- 架构文档: `docs/architecture.md`
- 部署指南: `docs/deploy-guide.md`
- 测试指南: `docs/testing-guide.md`
- 许可证: MIT

---

> 欢迎 Issue、PR、Star。让 Agent 真正记住你。
