# Memo 项目本地部署与同步指南

> 2026-06-29 改造记录 · 作者：托马斯尔康 & Hanako

---

## 一、家里电脑同步（首次）

如果家里电脑还没有这个项目：

```bash
# 1. Clone 到本地
git clone https://github.com/adoublegirl-dev/memo.git D:\个人\Hanako项目文件\Memo_V0.1.0

# 2. 安装依赖
cd D:\个人\Hanako项目文件\Memo_V0.1.0\memo-project
pip install -r requirements.txt
pip install "mcp>=1.0"

# 3. 创建 .env 配置（填入 DeepSeek API Key）
echo OPENAI_API_KEY=sk-你的key > .env
echo OPENAI_BASE_URL=https://api.deepseek.com/v1 >> .env
echo MEMO_EXTRACTION_MODEL=deepseek-v4-flash >> .env

# 4. 初始化数据库 + 自检
$env:HF_ENDPOINT='https://hf-mirror.com'
python init_db.py
```

如果家里电脑已有项目，只需拉取更新：

```bash
cd D:\个人\Hanako项目文件\Memo_V0.1.0
git pull
```

---

## 二、启动 MCP Server

```bash
cd D:\个人\Hanako项目文件\Memo_V0.1.0\memo-project
$env:HF_ENDPOINT='https://hf-mirror.com'
python run_mcp.py
```

MCP 客户端配置（Claude Desktop / Cursor / HanaAgent）：

```json
{
  "mcpServers": {
    "memo": {
      "command": "python",
      "args": ["D:\\个人\\Hanako项目文件\\Memo_V0.1.0\\memo-project\\run_mcp.py"],
      "env": { "HF_ENDPOINT": "https://hf-mirror.com" }
    }
  }
}
```

---

## 三、6/29 改造内容

### 3.1 重构包结构

原始代码为扁平布局，所有 .py 文件混放在一起，但导入语句使用 `memo.core.engine` 等包路径。按 architecture.md 描述的架构重建为标准 Python 包结构：

```
memo-project/
├── memo/                    # Python 包
│   ├── core/                # 引擎入口 + 配置
│   │   ├── config.py
│   │   └── engine.py
│   ├── store/               # 存储层
│   │   ├── database.py      # SQLite + 迁移
│   │   ├── graph_store.py   # 特征关系图谱
│   │   ├── memory_store.py  # 记忆单元 CRUD
│   │   ├── vector_store.py  # 向量索引
│   │   └── migrations/      # SQL 迁移文件
│   ├── utils/               # 工具层
│   │   ├── embedding.py     # BGE 嵌入模型
│   │   ├── llm.py           # LLM 客户端
│   │   └── logger.py        # 日志
│   ├── models/              # 数据模型 ★ 新增
│   │   └── __init__.py
│   ├── mcp/                 # MCP Server
│   ├── retrieval/           # 检索层（三通道+融合）
│   ├── extraction/          # LLM 提取器
│   └── lifecycle/           # 生命周期（遗忘/固化/快照）
├── init_db.py               # 初始化+自检
├── run_mcp.py               # MCP 启动入口
├── quick_check.py           # 快速自检（不依赖 LLM）
└── pyproject.toml
```

### 3.2 补全数据模型（memo/models）

GitHub 原始仓库缺失 `memo/models` 模块——FeatureTag、MemoryUnit、FeatureRelation 等核心类只有 import 语句，没有定义文件。根据 `architecture.md` §3 六维存储模型完整补全：

| 模型 | 说明 |
|---|---|
| `FeatureTag` | 特征词（Bjork 双强度遗忘模型，is_dormant 休眠标记） |
| `FeatureRelation` | 特征关系（图的边，赫布权重） |
| `MemoryUnit` | 记忆单元（六维存储核心：标题/特征词/摘要/二级摘要/原文/向量嵌入） |
| `Session` | 会话 |
| `TagMention` | 特征词↔记忆单元关联 |
| `GlobalMemorySnapshot` | 全局记忆快照 |
| `MemoryType` / `RelationType` / `SessionStatus` 等枚举 | |
| `RELATION_TYPE_FACTOR` | 扩散激活系数常量 |

### 3.3 上下文感知提取（★ 核心改造）

**改造前**：`memo_remember` 只存储传入的那段 `conversation` 原文，不会参考同会话中之前的对话。

**改造后**：新增 `context_rounds` 参数（默认 3），提取时自动回顾同会话最近 N 轮对话原文，LLM 判断是否有补充信息需纳入当前记忆。

涉及文件：
- `memo/extraction/extractor.py` — prompt 增加「之前的对话上下文」区域
- `memo/core/engine.py` — `remember_conversation` 新增 Step 0「回顾上下文」，查询同 session 最近 memory 的 raw_text
- `memo/mcp/server.py` — MCP 工具暴露 `context_rounds` 参数

**验证结果**（三连写场景）：

| 轮次 | context_rounds | LLM 表现 |
|:---:|:---:|---|
| 1 | 0 | 正常提取（无历史） |
| 2 | 1 | 「**基于之前对 PostgreSQL 和 MySQL 的讨论**，用户决定采用 PostgreSQL...」 |
| 3 | 2 | 「为 PostgreSQL 用户表...」「**基于防刷检查需求**，决定建联合索引」 |

LLM 自行判断前情有用则纳入摘要，无补充则保留当前片段，不是机械拼接。

### 3.4 路径修复

- `config.py`：加入 `_PROJECT_ROOT` 常量，适配新包层级
- `run_mcp.py`：`parent.parent` → `parent`
- `quick_check.py`：硬编码 `E:/memo` → 动态路径

### 3.5 环境配置

- 依赖：`sentence-transformers`（含 torch）、`mcp>=1.0`
- HuggingFace：设置 `HF_ENDPOINT=https://hf-mirror.com` 国内镜像下载 BGE 模型
- LLM：配置 DeepSeek API（`OPENAI_BASE_URL=https://api.deepseek.com/v1`，模型 `deepseek-v4-flash`）
- `.gitignore`：排除 `.env`、`data/`、`__pycache__/`

---

## 四、MCP 工具清单

| 工具 | 功能 |
|---|---|
| `memo_start_session` | 开始新会话 |
| `memo_end_session` | 结束会话 |
| `memo_remember` | 写入记忆（支持 `conversation` 自动提取 + `context_rounds` 上下文感知） |
| `memo_recall` | 三通道混合检索（向量 + BM25 + 图扩散激活） |
| `memo_stats` | 系统统计 |
| `memo_hot_tags` | 高频特征词 |
| `memo_maintain` | 生命周期维护 |
| `memo_snapshot` | 全局快照 |
