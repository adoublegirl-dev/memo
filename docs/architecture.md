# Memo（麦默）—— Agent 记忆系统架构设计

> **命名**：Memo，取"记忆（memory）"之音，中文"麦默"——麦子成熟时沉默低头，记忆亦如此：重者沉底，轻者浮散。
>
> **定位**：为 AI Agent 提供活的、会进化的、跨会话的网状记忆层。不是静态索引，而是一张会呼吸的记忆网。
>
> **设计原则**：好用 > 完整。每个功能上线前必须通过"实际检索是否比直接翻聊天记录更快更准"这一关。

---

## 一、核心架构总览

```
┌─────────────────────────────────────────────────────────────────────┐
│                          Agent 运行时                                 │
│                                                                      │
│  用户输入 ──▶ [记忆检索] ──▶ 上下文注入 ──▶ LLM 回复                    │
│                  │                                                   │
│  对话结束 ──▶ [记忆写入] ──▶ 后台异步管道                               │
└─────────────────────────────────────────────────────────────────────┘

                         记忆系统内部三通道

┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│   通道①           │  │   通道②           │  │   通道③           │
│   向量语义检索     │  │   全文关键词检索    │  │   图扩散激活检索    │
│   cosine ~ 50ms   │  │   BM25 ~ 30ms    │  │   Hebbian Graph  │
│                    │  │                   │  │   BFS ~ 100ms    │
└──────┬───────────┘  └──────┬───────────┘  └──────┬───────────┘
       │                     │                     │
       └─────────────────────┼─────────────────────┘
                             │
                    ┌────────▼────────┐
                    │   RRF 融合排序   │
                    │   Reciprocal    │
                    │   Rank Fusion   │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  可选 LLM 重排   │
                    │  (GPT-4o-mini)  │
                    └────────┬────────┘
                             │
                         Top-K 结果
                         (默认 5 条)
```

---

## 二、记忆的三层架构

### L0 热记忆体（Core Memory）

**类比**：计算机的 L1 缓存 / 人脑的工作记忆

| 属性 | 说明 |
|------|------|
| 存储内容 | 高频特征词（top 50）+ 最近 3 个会话的摘要 + 当前活跃子图（特征词及 1 跳邻居） |
| 存储介质 | 进程内存（Python dict）+ 可选 Redis |
| 检索延迟 | <10ms |
| 更新频率 | 每个会话结束即时更新 |
| 容量上限 | ~10,000 条特征词 + ~500 条记忆片段 |

**L0 预加载策略**：
- Agent 启动时从 L1 拉取权重最高的 50 个特征词注入 L0
- 用户首条消息时做快速特征词匹配，命中即预热相关子图
- 会话进行中，L0 持续更新被激活的特征词

### L1 温记忆体（Feature Relationship Graph）★ 核心差异化

**类比**：人脑的语义记忆网络

| 属性 | 说明 |
|------|------|
| 存储内容 | 特征词库 + 特征关系图谱（边权重动态更新）+ 所有摘要 + 二级摘要 |
| 存储介质 | SQLite（图结构用邻接表存储） |
| 检索延迟 | 100-500ms |
| 更新频率 | 实时（每次 conversation 后写边权重）、每日 consolidation |

**L1 是"大脑皮层"——最核心的部分。** 所有跨会话关联、网状扩散、权重进化都在这一层发生。

### L2 冷存储（Archival Memory）

**类比**：档案库 / 人脑的长期记忆

| 属性 | 说明 |
|------|------|
| 存储内容 | 完整对话原文 + 历史事实（含过期/失效） + 嵌入向量 |
| 存储介质 | SQLite（原文）+ pgvector 扩展 |
| 检索延迟 | 1-5 秒 |
| 更新频率 | 写入即时、读取按需 |

---

## 三、六维存储模型

### 数据实体关系图

```
┌──────────┐        ┌──────────────┐        ┌──────────────┐
│  Session  │1──────N│ MemoryUnit   │N──────M│ FeatureTag   │
│  (会话)   │        │ (记忆单元)    │        │ (特征词)      │
└──────────┘        └──────┬───────┘        └──────┬───────┘
                           │                       │
                           │ DERIVED_FROM          │ CO_OCCUR
                           │ (派生关系)             │ (共现关系)
                           │                       │
                    ┌──────▼───────┐        ┌──────▼───────┐
                    │   Summary    │        │ FeatureTag    │
                    │   摘要/二级    │        │   另一个特征词  │
                    └──────────────┘        └──────────────┘
```

### 3.1 会话（Session）

```python
Session:
    id: str                    # UUID
    agent_id: str              # 所属 Agent
    title: str                 # 标题（人工或 LLM 自动生成）
    created_at: datetime       # 创建时间
    ended_at: datetime | None  # 结束时间
    status: enum(active, completed, archived)
    memory_count: int          # 包含的记忆单元数量
```

### 3.2 特征词（FeatureTag）★ 最关键的数据结构

```python
FeatureTag:
    id: str                    # UUID
    name: str                  # 特征词文本（如"排位赛"、"ELO算法"）
    category: enum             # POLE+O 分类：PERSON/OBJECT/LOCATION/EVENT/ORGANIZATION/CONCEPT
    # ── 双强度遗忘（Bjork 模型）────
    storage_strength: float    # 存储强度 [0,1]，只增不减
    retrieval_strength: float  # 检索强度 [0,1]，不用时衰减
    # ── 赫布权重 ────
    total_activations: int     # 总激活次数
    last_activated_at: datetime
    cooldown_days: float       # 距上次激活的天数
    # ── 元数据 ────
    first_seen_at: datetime    # 首次出现时间
    created_by: enum(LLM_AUTO, USER_MANUAL)
    embedding: float[768]      # 向量嵌入（BGE-small-zh）
```

**双强度遗忘**：`storage_strength` 只增不减（每次激活+0.01），`retrieval_strength` 不用时每天衰减 2%。检索时二者相乘得有效权重。这避免了"很久没提但很重要的事"被误删。

### 3.3 特征关系（FeatureRelation）★ 图的边

```python
FeatureRelation:
    id: str
    source_tag_id: str         # 源特征词
    target_tag_id: str         # 目标特征词
    relation_type: enum        # CO_OCCUR / DERIVED / CAUSAL / TEMPORAL / CONTRADICT
    hebbian_weight: float      # 赫布边权重 [0,1]
    co_activation_count: int   # 共激活次数
    last_co_activated_at: datetime
    first_observed_at: datetime
    contexts: list[str]        # 首次共现的上下文（最多 3 条，用于调试）
```

**赫布权重更新公式**：

```
Δw = η × (1 - w) × S_semantic × co_occurrence_boost

其中:
  η = 0.05                    # 学习率
  w = 当前 hebbian_weight
  S_semantic = cosine(embedding_A, embedding_B)
  co_occurrence_boost = min(co_activation_count / 10, 2.0)
```

### 3.4 记忆单元（MemoryUnit）

```python
MemoryUnit:
    id: str                    # UUID
    session_id: str            # 所属会话
    # ── 六维存储核心 ────
    title: str                 # ① 标题
    feature_tags: list[str]    # ② 关联特征词 ID 列表
    summary: str               # ③ 一级摘要（≤300 字符）
    summary_detail: str        # ④ 二级摘要（≤1500 字符）
    raw_text: str              # ⑤ 原文
    # ── 时序信息 ────
    valid_from: datetime       # 事实生效时间
    valid_until: datetime | None  # 事实失效时间
    recorded_at: datetime      # 系统记录时间
    is_superseded: bool        # 是否已被新事实替代
    superseded_by: str | None  # 替代此条的记忆单元 ID
    # ── 置信度 ────
    confidence: float          # [0,1]
    # ── 类型 ────
    memory_type: enum          # FACT / DECISION / PREFERENCE / EVENT / REASONING
    # ── 元数据 ────
    embedding: float[768]      # 向量嵌入
```

### 3.5 特征词↔记忆单元关联（TagMention）

```python
TagMention:
    id: str
    tag_id: str                # 特征词 ID
    memory_unit_id: str        # 记忆单元 ID
    mention_type: enum         # DIRECT / INFERRED / TITLE
    relevance_score: float     # [0,1]
    position_index: int        # 在对话中出现的位置
```

### 3.6 系统级记忆快照（GlobalMemorySnapshot）

```python
GlobalMemorySnapshot:
    id: str
    agent_id: str
    snapshot_at: datetime
    total_sessions: int
    total_memory_units: int
    total_feature_tags: int
    total_relations: int
    agent_profile: str         # Agent 对用户的全局认知（≤1000 字符）
    top_domains: list[str]     # 用户最常涉足的领域
    active_projects: list[str] # 当前活跃项目/话题
    hot_tags: list[str]        # 当前高频特征词 ID（top 50）
    recent_important_memories: list[str]  # 近期重要记忆 ID
```

快照触发：每 50 条新记忆 OR 每 7 天。保留最近 10 个快照。

---

## 四、检索算法：三通道 + 扩散激活

### 4.1 通道①：向量语义检索

1. 用 BGE-small 编码 query → embedding_q (768-dim)
2. 在 MemoryUnit.embedding 做 cosine 相似度搜索
3. 返回 top-20

### 4.2 通道②：全文 BM25 检索

1. 对 query 做分词（jieba 中文）
2. 用 SQLite FTS5 全文匹配
3. 返回 top-20

### 4.3 通道③：图扩散激活检索 ★ 核心创新

```
算法：赫布扩散激活 (Hebbian Spreading Activation)

Step 1: 入口节点定位
  从 query 中提取特征词 → seed_tags
  初始化 activation_map = {tag_id: 1.0 for tag_id in seed_tags}

Step 2: 扩散激活（BFS，max_hops=3, decay_rate=0.5）
  for hop in range(3):
    for (tag_id, activation) in activation_map:
      neighbors = graph.get_neighbors(tag_id)
      for neighbor in neighbors:
        edge = graph.get_edge(tag_id, neighbor)
        propagation = activation × 0.5 × edge.hebbian_weight × relation_type_factor
        new_activations[neighbor] = max(existing, propagation)
  
  归一化: activation /= max_activation

Step 3: 着陆（特征词 → 记忆单元）
  for (tag_id, activation) in activation_map:
    mentions = graph.get_tag_mentions(tag_id)
    for mention in mentions:
      memory_scores[mention.memory_unit_id] += activation × mention.relevance_score

Step 4: 排序返回 top-15
```

**扩散系数**：CO_OCCUR=1.0, CAUSAL=2.0, TEMPORAL=1.2, DERIVED=0.8

### 4.4 RRF 融合

```
RRF_score(doc) = Σ 1 / (60 + rank_channel(doc))
```

### 4.5 可选 LLM 重排

top-10 中分差 < 0.05 的相邻对，用 GPT-4o-mini 重排。500ms 超时，不可用时降级。

---

## 五、记忆生命周期

### 5.1 写入管道（实时）

```
对话片段 → [LLM 提取] → 特征词/摘要/关系 → [冲突检测] → [写入 L1+L2] → [更新 L0]
```

单次 LLM 调用完成全部提取（特征词 + 摘要 + 关系 + 冲突检测），输出 JSON。

### 5.2 Consolidation 管道（阈值触发）

触发：未固化记忆单元 ≥ 10 条。

流程：主题聚类 → 矛盾检测（双时序处理）→ 重复识别 → 写回 L1 → 更新特征词库（合并同义词、重算赫布权重、更新 storage_strength）。

### 5.3 遗忘管道（每日定时）

```
Step 1: 检索强度衰减
  retrieval_strength *= (1 - 0.02 × days_since_last_activation)

Step 2: 三维度修剪
  同时满足 → 标记"休眠"：
  (1) 有效权重 < 0.05
  (2) 休眠天数 > 90
  (3) 近 30 天访问次数 = 0

Step 3: 归档
  休眠特征词从 L1 → L2（不删除，可恢复）
```

---

## 六、技术栈

| 组件 | 选择 | 理由 |
|------|------|------|
| **编程语言** | Python 3.12 | LLM 生态最丰富 |
| **数据库** | SQLite + 自建向量索引 | 零配置、单文件、够用 |
| **嵌入模型** | BGE-small-zh-v1.5（768-dim） | 中文友好、本地跑 |
| **LLM 提取** | GPT-4o-mini API | 轻量即可 |
| **图计算** | 自建（邻接表） | 1-10万量级不需 Neo4j |
| **对外接口** | MCP Server（stdio） | Agent 通用协议 |

---

## 七、开发路线图

| Phase | 内容 | 天数 |
|:---:|------|:---:|
| 0 | 基础设施：数据库、数据模型、嵌入模型、LLM 封装 | 1-2 |
| 1 | 写入管道：LLM 提取、去重、冲突检测 | 2-3 |
| 2 | 检索三通道：向量、BM25、图扩散、RRF 融合 | 3-4 |
| 3 | 赫布学习 + 遗忘 + Consolidation + 快照 | 2-3 |
| 4 | MCP Server + Agent 集成 | 1-2 |
| 5 | 优化：延迟、压测、参数调优 | 持续 |

---

## 八、关键参数默认值

| 参数 | 值 | 说明 |
|------|:---:|------|
| `hebbian_learning_rate` | 0.05 | 赫布学习率 |
| `co_occurrence_boost_cap` | 2.0 | 共现加成上限 |
| `spreading_decay_rate` | 0.5 | 扩散衰减率 |
| `spreading_max_hops` | 3 | 最大扩散跳数 |
| `retrieval_strength_decay` | 0.02/天 | 检索强度衰减 |
| `storage_strength_increment` | 0.01/次 | 存储强度增量 |
| `dormant_threshold_days` | 90 | 休眠天数阈值 |
| `consolidation_trigger_count` | 10 | 固化触发数 |
| `snapshot_trigger_count` | 50 | 快照触发数 |
| `embedding_dim` | 768 | 嵌入维度 |
| `top_k_retrieval` | 5 | 默认返回数 |
| `rrf_k` | 60 | RRF 参数 |

---

> 最后更新：2026-06-27
> 作者：托马斯尔康 & Hanako
> 状态：Phase 0 开发中
