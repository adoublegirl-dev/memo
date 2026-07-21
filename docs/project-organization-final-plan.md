# Memo 项目整理优化最终方案

更新时间：2026-07-21

## 1. 目标

把 Memo 中已经沉淀的会话、记忆和待办，整理成可治理的 Context Space，让 Memo 不只是“记住很多东西”，还能把内容按真实项目、产品线、客户、管理事项、写作主题等空间聚合起来。

本方案强调：

```text
整理归整理，权重归权重。
```

项目整理层只建立来源和归属映射，不改变记忆本体的重要性、检索权重和用户治理状态。

---

## 2. 当前已实现版本

当前实现链路：

```text
memo.sessions
  ↓ 扫描 session 下的 memory/todo/tag
space_candidates
  ↓ 用户手动确认 / 合并 / 忽略
spaces + space_memories + todos.space_id + sessions.space_id
```

### 2.1 `sessions`：当前来源基础

当前 Space Candidate 以 Memo 内部 `sessions` 为扫描单位。

扫描规则：

- 忽略 `archived` session。
- 只统计 active memory，排除 `deleted` / `wrong` / `muted`。
- 已经进入候选决策链的 session 不重复扫描。
- `min_memories` 控制候选最低记忆数量。

局限：

- `sessions` 仍是 Memo 内部会话模型。
- 还不能准确区分真实 Agent 会话、自动同步会话、Bridge 导入会话。
- 因此当前候选质量依赖 session 标题、记忆摘要、标签和待办线索。

### 2.2 `space_candidates`：候选项目层

`space_candidates` 是系统建议，不是正式 Space。

它记录：

- 候选名称
- 候选类型
- 描述
- 置信度
- 来源 session ids
- 来源 memory ids
- 来源 todo ids
- 建议别名
- 建议合并到的已有 Space
- 候选之间的合并建议
- 状态和决策审计

候选扫描可以使用规则，也可以可选使用 LLM 轻量优化命名。

LLM 约束：

- 只读取摘要、标签、待办标题。
- 不读取完整 raw_text 做扩展发挥。
- 只用于命名和边界描述，不直接创建正式 Space。

### 2.3 用户确认层

候选项目只有经过用户手动动作才进入正式治理对象：

| 动作 | 结果 |
|---|---|
| accept | 创建新 Space，并绑定来源 memory/todo/session |
| merge_to_space | 合并到已有 Space，并绑定来源 |
| merge_many | 多个候选合并为一个新 Space |
| ignore | 忽略候选，不做绑定 |

确认/合并时写入：

- `spaces`
- `space_aliases`
- `space_memories`
- `todos.space_id`
- `sessions.space_id`
- `space_candidate_audit_logs`

---

## 3. 权重边界

Space Candidate 流程不负责判断“这条记忆是否更重要”。它只回答：

```text
这条记忆/待办/会话应该归到哪个 Space？
```

### 3.1 不允许修改的字段

当前和后续项目整理流程不得修改：

```text
memory_units.signal_level
memory_units.user_weight
memory_units.pinned
memory_units.status
feature_relations.hebbian_weight
feature_tags.storage_strength
feature_tags.retrieval_strength
feature_relations.last_session_id
memory_units.raw_text/title/summary/summary_detail
```

### 3.2 允许修改的映射字段

项目整理确认动作允许修改：

```text
space_candidates.status / decision_*
space_memories(space_id, memory_id, relation_type, relevance)
todos.space_id
todos.space_relation_type
sessions.space_id（仅 COALESCE，不覆盖已有 Space）
spaces.memory_count / todo_count / session_count / last_active_at
space_candidate_audit_logs
```

### 3.3 如果未来需要权重治理

如果后续希望“某个 Space 内的记忆更重要”，不能隐式塞进候选确认流程。

必须作为单独显式功能：

```text
用户点击治理动作 → 写 memory_audit_logs → 修改 user_weight/status/pinned
```

这样可以保持：

- 项目整理可回溯
- 记忆治理可审计
- 用户不会因为确认 Space 候选而意外改变检索排序

---

## 4. 目标版本：source_sessions 来源层

当前方案仍基于 `sessions`。下一阶段建议新增 `source_sessions`，形成更清晰的来源治理架构。

目标链路：

```text
真实 Agent 对话 / Bridge 导入 / 自动同步文件
  ↓
source_sessions
  ↓ 映射
memory_units / todos / sessions
  ↓ 扫描整理
space_candidates
  ↓ 用户确认
spaces
```

### 4.1 为什么需要 `source_sessions`

当前 `sessions` 容易混合多种来源：

- HanaAgent 真实对话
- WorkBuddy 真实对话
- Qoder 真实对话
- Bridge 导入
- watcher 自动同步
- 内部工具写入

如果直接基于 `sessions` 做项目整理，可能出现：

```text
自动同步会话被当成真实项目会话
同一真实会话被多个导入链路拆散
来源 Agent 和实际内容边界不清
```

`source_sessions` 的作用是建立真实来源索引，而不是替代记忆。

### 4.2 建议字段

建议 `source_sessions` 至少包含：

```text
id
source_type          # hanaagent / workbuddy / qoder / claude / bridge / watcher / manual
source_agent
external_session_id
external_thread_id
source_path
title
started_at
ended_at
imported_at
message_count
memory_count
content_hash
status
metadata_json
```

可选映射表：

```text
source_session_memories(source_session_id, memory_id, relation_type)
source_session_todos(source_session_id, todo_id, relation_type)
```

### 4.3 迁移原则

- additive migration only。
- 不删除旧 `sessions`。
- 不强行把旧数据一次性分类。
- 初期允许 `source_sessions` 为空，只对新导入/新同步链路写入。
- 历史数据可通过候选/回填工具渐进补齐。

---

## 5. Dashboard 交互建议

### 5.1 Space Candidate 页面

每个候选卡片应展示：

- 候选名称
- 置信度
- 来源 session 数
- 来源 memory 数
- 来源 todo 数
- 关键词
- 建议合并对象
- 合并候选
- 审计记录

用户动作：

```text
确认为新 Space
合并到已有 Space
多个候选合并
忽略
查看来源证据
```

### 5.2 风险提示

候选确认按钮附近建议显示：

```text
确认只会建立 Space 绑定，不会改变记忆权重、置顶或重要性。
```

这样能降低用户对“整理会不会污染记忆”的担心。

---

## 6. 验证标准

### 6.1 代码级验证

至少覆盖：

- 扫描候选只生成 `space_candidates`。
- accept 后能在 `space_recall(..., mode='within')` 检索到来源记忆。
- merge_many 后所有来源记忆进入同一 Space。
- accept/merge 不改变 `signal_level` / `user_weight` / `pinned`。
- ignore 不创建 Space，不绑定 memory/todo/session。

### 6.2 数据级验证

生产库升级后检查：

```sql
SELECT version FROM schema_version ORDER BY version DESC LIMIT 1;
SELECT COUNT(*) FROM space_candidates;
SELECT COUNT(*) FROM spaces;
```

候选扫描前，`space_candidates` 可以为 0。扫描后才会生成候选。

---

## 7. 推荐推进顺序

### P0：当前版本收口

1. 确认权重边界。
2. 固化最终方案文档。
3. 给 Dashboard 候选操作增加说明。
4. 增加“不改权重”测试。

### P1：source_sessions 来源层

1. 新增 migration。
2. 让导入/同步链路写 `source_sessions`。
3. 增加 source → memory/todo 映射。
4. Dashboard 显示真实来源会话。

### P2：候选质量优化

1. 自动同步类来源降噪。
2. 候选合并建议增强。
3. 批量忽略/合并。
4. 低置信候选进入待确认队列，不自动展示为强建议。

### P3：与记忆治理联动

1. Space 视角展示重复候选。
2. semantic duplicate candidate queue 只做候选。
3. 用户显式治理后才修改记忆状态或权重。

---

## 8. 最终原则

```text
Space 是组织层，不是权重层。
Candidate 是建议层，不是自动决策层。
source_sessions 是来源层，不是记忆本体。
用户确认是治理边界，所有隐式自动化都必须可审计、可撤销。
```
