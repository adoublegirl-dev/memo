# Memo 测试指南

> 三种方法，由简到繁，任选一种即可验证。

---

## 方法一：Python 直接调用（最快，1 分钟）

不依赖 MCP、不依赖 API Key，直接在命令行跑。

```powershell
cd E:\memo
python tests/test_integration_phase1.py
```

**你会看到：**
- 自动创建 2 个模拟会话
- 写入 3 条记忆（用 jieba 自动提取特征词）
- 5 条查询验证检索结果
- 统计信息和生命周期报告

**预期输出：**
```
📁 会话 1：排位赛系统开发
  ✓ 记忆: 我想在炸飞机游戏里加入排位赛系统
  ✓ 特征词: ['段位', '排位赛', 'ELO', ...]

🔍 查询: 排位赛的 ELO 初始分是多少？
  1. [0.0164] 排位赛之外我还想做个天梯赛...
     特征词: 天梯, 排位赛, ELO

Phase 1 集成测试通过！✅
```

---

## 方法二：MCP Server 冒烟测试（检查工具列表）

验证 MCP 协议的 8 个工具都能正常响应。

```powershell
cd E:\memo
python tests/test_mcp_smoke.py
```

**你会看到：**
```
✓ 工具列表: 8 个
  - memo_remember
  - memo_recall
  ...（全部 8 个工具名）

✅ memo_stats({})
✅ memo_remember({"conversation": "..."})
✅ memo_recall({"query": "MCP Server 测试", "top_k": 3})
...（每个工具调用一次，全部 ✅）

MCP Server 冒烟测试通过！
```

---

## 方法三：真实 MCP 客户端测试（推荐）

这是最接近生产环境的测试方式。用 MCP Inspector 或直接接入 Claude Desktop。

### 3.1 安装 MCP Inspector

```powershell
npm install -g @modelcontextprotocol/inspector
```

### 3.2 启动 Inspector

```powershell
npx @modelcontextprotocol/inspector python E:/memo/scripts/run_mcp.py
```

浏览器会自动打开 `http://localhost:5173`。

**在 Inspector 界面中：**
1. 点击 **Tools** 标签页，看到 8 个工具
2. 点击 `memo_stats` → **Run** → 看到统计信息
3. 点击 `memo_remember` → 填入参数：
   ```json
   {
     "conversation": "我是Memo开发者，正在开发一个记忆系统，叫 Memo。它用赫布学习和扩散激活来做网状记忆图谱。"
   }
   ```
   → **Run** → 看到提取结果
4. 再写一条：
   ```json
   {
     "conversation": "Memo 的三通道检索包括向量语义、BM25 全文、图扩散激活，用 RRF 融合。特征词之间用赫布权重连接。"
   }
   ```
   → **Run**
5. 点击 `memo_recall` → 填入：
   ```json
   {
     "query": "Memo 的检索是怎么做的？"
   }
   ```
   → **Run** → 看到两条记忆都被命中，特征词形成了关联
6. 点击 `memo_hot_tags` → **Run** → 看到高频特征词排行
7. 点击 `memo_snapshot` → **Run** → 看到全局快照

### 3.3 可选：配 API Key 启用 LLM 提取

编辑 `.env`（从 `.env.example` 复制）：

```env
LLM_API_KEY=sk-your-real-key
```

重启 Inspector，再写入记忆时会看到 `提取方式: llm`，特征词质量远高于 jieba。

---

## 方法四：接入 HanaAgent（真实验证）

### 4.1 添加 MCP 配置

在 HanaAgent 的 MCP 配置中添加 Memo：

```json
{
  "mcpServers": {
    "memo": {
      "command": "python",
      "args": ["<项目路径>/scripts/run_mcp.py"],
      "env": {
        "LLM_API_KEY": "sk-...",
        "MEMO_DB_PATH": "<项目路径>/memo/data/memo.db"
      }
    }
  }
}
```

### 4.2 开始对话测试

对 HanaAgent 说：

> **第一轮（写入）**：「帮我记住，我正在做一个叫"炸飞机"的联机对战游戏，已经实现了排位赛和天梯赛，ELO 初始分 1200，K 值 32。」

ASH 会调用 `memo_remember`，自动提取特征词（炸飞机、排位赛、天梯赛、ELO 算法...）并写入。

> **第二轮（跨会话检索）**：新开一个会话，问：「之前那个游戏的匹配算法参数是什么？」

ASH 会调用 `memo_recall("匹配算法参数")` → 三通道检索 → 返回第一轮的记忆 → 正确回答。

> **第三轮（图关联验证）**：新会话问：「除了排位赛还有什么竞技模式？」

ASH 调用 `memo_recall`，通过特征词图谱的 CO_OCCUR 关系，发现"排位赛"和"天梯赛"有强关联，自动关联返回。

---

## 关键验证点清单

| # | 验证点 | 预期 | 方法 |
|---|--------|------|:---:|
| 1 | 数据库初始化 | 8 张表 + FTS5 索引创建成功 | 方法一 |
| 2 | 记忆写入 | 对话→特征词/摘要/关系，写入 L1+L2 | 方法一/三 |
| 3 | 向量编码 | 每条记忆编码并记入向量索引 | 方法一 |
| 4 | 特征词激活 | 写入时自动创建/激活特征词，更新权重 | 方法一 |
| 5 | 赫布关系 | 同一条记忆的特征词自动建立 CO_OCCUR 边 | 方法一 |
| 6 | 向量检索 | 语义相似查询命中相关记忆 | 方法一/三 |
| 7 | 图扩散激活 | 通过特征词关联找到跨会话相关记忆 | 方法三/四 |
| 8 | RRF 融合 | 三通道结果合并，排序合理 | 方法一/三 |
| 9 | 遗忘衰减 | 每日衰减检索强度，休眠条件触发 | 需多天或手动调参 |
| 10 | 双时序替代 | 新事实标记旧事实 is_superseded | 需 LLM |
| 11 | MCP 工具列表 | 8 个工具可发现 | 方法二/三 |
| 12 | MCP 工具调用 | 每个工具输入输出正确 | 方法三 |
| 13 | 跨会话检索 | 新会话能检索到旧会话的记忆 | 方法四 |

---

## 无 API Key 时的降级行为

| 功能 | 有 API Key | 无 API Key |
|------|-----------|-----------|
| 特征词提取 | LLM 提取 3-8 个高质量词 | jieba TF-IDF 提取 1-6 个词 |
| 摘要生成 | LLM 总结 | 截取前 300 字符 |
| 关系提取 | LLM 判断因果/派生关系 | 仅 CO_OCCUR |
| 冲突检测 | LLM 语义判断 | 不执行 |
| 检索重排 | 可选 LLM 重排 top-N | 跳过重排 |

**无 API Key 也能完整跑通所有核心流程。** LLM 只是提升提取质量，不阻塞功能。

---

## 快速命令速查

```powershell
# 基础自检（不依赖 LLM）
python E:\memo\scripts\quick_check.py

# 集成测试（模拟多会话）
python E:\memo\tests\test_integration_phase1.py

# MCP 冒烟测试
python E:\memo\tests\test_mcp_smoke.py

# 启动 MCP Server（配到 Agent 用）
python E:\memo\scripts\run_mcp.py

# 清空数据库重新测试
Remove-Item E:\memo\memo\data\memo.db -Force
```
