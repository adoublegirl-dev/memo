# Memo（麦默）

> 活的、会进化的 Agent 记忆系统。赫布学习 + 扩散激活 + 网状记忆图谱。

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 LLM（可选，用于自动提取）
cp .env.example .env
# 编辑 .env，填入 OPENAI_API_KEY

# 3. 初始化数据库
python scripts/init_db.py

# 4. 基础自检（不依赖 LLM）
python scripts/quick_check.py
```

## 使用

```python
from memo import engine

engine.init()

# 开始会话
session = engine.start_session(title="合同审查")

# 写入记忆（自动提取特征词、建立关系）
engine.remember(
    session_id=session.id,
    raw_text="审查了甲方的采购合同，发现第12条违约责任条款对乙方不利，建议修改为对等责任...",
    feature_tags=["合同审查", "违约责任", "采购合同"],
    tag_relations=[
        {"from": "违约责任", "to": "合同审查", "type": "CAUSAL"},
    ],
)

# 检索记忆（三通道：向量+全文+图扩散）
results = engine.recall("之前那个采购合同的违约责任条款怎么说的？")
for r in results:
    print(f"[{r['score']:.4f}] {r['title']}")

# 生命周期维护
engine.run_lifecycle()
```

### MCP Server

```bash
# 启动 MCP Server（stdio）
python scripts/run_mcp.py
```

配置 Claude Desktop / Cursor / Claude Code:

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

提供 8 个 MCP 工具：`memo_remember` / `memo_recall` / `memo_start_session` / `memo_end_session` / `memo_stats` / `memo_hot_tags` / `memo_maintain` / `memo_snapshot`

## 架构

三层记忆 + 六维存储 + 三通道检索。详见 `docs/architecture.md`。

## 目录

```
memo/
├── memo/               # 核心包
│   ├── core/           # 引擎入口 + 配置
│   ├── models/         # 数据模型
│   ├── store/          # 存储层（数据库/图/向量）
│   ├── retrieval/      # 检索层（三通道+融合）
│   ├── extraction/     # LLM 提取器
│   ├── lifecycle/      # 生命周期（遗忘/固化/快照）
│   ├── mcp/            # MCP Server（8 个工具）
│   └── utils/          # 嵌入、LLM、日志
├── docs/               # 文档
├── scripts/            # 运维脚本
├── tests/              # 测试
└── data/               # 数据库文件
```

## 状态

Phase 0-4 完成。

- ✅ Phase 0: 基础设施
- ✅ Phase 1: LLM 提取管道
- ✅ Phase 2: 检索三通道（向量+BM25+图扩散）
- ✅ Phase 3: 赫布学习 + 遗忘 + 生命周期
- ✅ Phase 4: MCP Server（8 个核心工具）
- ⬜ Phase 5: 优化与打磨

## 许可

MIT
