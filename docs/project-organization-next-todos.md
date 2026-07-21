# 项目整理优化后续待办

更新时间：2026-07-21

## 已确认结论

### 1. Memo 项目整理涉及的权重规则边界

已核对 `memo/space/candidates.py`、`memo/store/migrations/015_space_candidates.sql`、`memo/core/engine.py` 相关入口和现有测试。

结论：**当前 Space Candidate 项目整理流程不修改记忆权重字段，不重写已有 `memo.sessions` 语义。**

#### 当前实现会写入/更新的表

| 阶段 | 表 | 操作 | 说明 |
|---|---|---|---|
| 扫描候选 | `space_candidates` | `INSERT` / `UPDATE` | 记录候选项目名称、来源 session/memory/todo id、合并建议 |
| 扫描候选 | `space_candidate_audit_logs` | `INSERT` | 记录候选创建审计 |
| 确认候选 | `spaces` | `INSERT` | 创建正式 Space |
| 确认候选 | `space_aliases` | `INSERT OR IGNORE` | 写入候选名/关键词别名 |
| 确认/合并候选 | `space_memories` | `INSERT OR REPLACE` | 绑定 memory 到 Space，`relation_type='candidate_confirmed'` |
| 确认/合并候选 | `todos` | `UPDATE space_id, space_relation_type, updated_at` | 绑定待办到 Space |
| 确认/合并候选 | `sessions` | `UPDATE space_id = COALESCE(space_id, ?)` | 只给尚未绑定 Space 的 session 填充 Space |
| 确认/合并候选 | `spaces` | `UPDATE memory_count/todo_count/session_count/last_active_at/updated_at` | 刷新 Space 统计 |
| 忽略候选 | `space_candidates` | `UPDATE status/decision_*` | 标记 ignored/rejected 等决策结果 |
| 决策审计 | `space_candidate_audit_logs` | `INSERT` | 记录 accepted/merged/ignored 等动作 |

#### 当前实现不会修改的字段

| 权重/记忆本体字段 | 当前 Space Candidate 流程是否修改 | 结论 |
|---|---:|---|
| `memory_units.signal_level` | 否 | 不改变手动/自动/高价值记忆等级 |
| `memory_units.user_weight` | 否 | 不改变用户治理权重 |
| `memory_units.pinned` | 否 | 不改变置顶/重要标记 |
| `feature_relations.hebbian_weight` | 否 | 不改变赫布边权重 |
| `feature_tags.storage_strength` | 否 | 不改变存储强度 |
| `feature_tags.retrieval_strength` | 否 | 不改变检索强度 |
| `feature_relations.last_session_id` / session boost 相关逻辑 | 否 | 不参与候选确认，不重算 session boost |
| `memory_units.raw_text/title/summary/summary_detail` | 否 | 不重写记忆内容 |
| `sessions.title/status/created_at/memory_count` | 否 | 只补 `space_id`，且使用 `COALESCE` 避免覆盖已有绑定 |

### 边界原则固化

> Space Candidate 只做“项目整理映射”，不是“记忆权重治理”。

后续任何项目整理功能都必须遵守：

1. 候选扫描不得修改正式 Space 绑定，不得修改记忆权重。
2. 候选确认/合并只允许写映射层：`space_memories`、`todos.space_id`、`sessions.space_id`、审计日志和 Space 统计。
3. 不得在 Space Candidate 流程里修改 `signal_level` / `user_weight` / `pinned`。
4. 不得重算 `hebbian_weight` / `storage_strength` / `retrieval_strength`。
5. 若未来需要根据 Space 做权重策略，必须另起“显式治理动作”，并写入审计，不得混入候选确认流程。

---

## 最终版项目整理优化方案

详见：

```text
docs/project-organization-final-plan.md
```

核心结论：

```text
当前版：sessions → space_candidates → spaces
目标版：source_sessions → memory_units/todos → space_candidates → spaces
```

当前没有 `source_sessions` 表。`source_sessions` 是下一阶段来源治理层，用于区分真实 Agent 会话、自动同步会话、Bridge 导入会话等来源。当前实现仍基于 Memo 内部 `sessions`。

---

## 后续待办

### P0：保持当前 Space Candidate 稳定

- [x] 确认项目整理不触碰记忆权重字段。
- [x] 整理最终版项目整理优化方案。
- [ ] 在 Dashboard Spaces 页面继续完善候选扫描/确认/合并/忽略交互提示。
- [ ] 给候选确认动作增加更明显的“只绑定，不改权重”说明。

### P1：实现 `source_sessions` 来源会话层

目标：避免把“自动同步会话”和真实 Agent 会话混为一谈。

已完成基础层：

```text
source_sessions
source_session_memories
source_session_todos
```

当前实现边界：

- [x] 新增 additive migration `016_source_sessions.sql`。
- [x] 新增 `memo/space/source_sessions.py` 基础 Manager。
- [x] 支持从现有 `memo.sessions` 渐进 backfill 来源索引。
- [x] Space Candidate 扫描时旁路建立 source session 索引。
- [x] Dashboard 增加“更新来源索引”入口和“不改权重”提示。
- [x] 增加 source session 基础回归测试。
- [ ] 导入/同步链路直接写入真实外部 `source_sessions`，减少对 legacy `sessions` 的依赖。
- [ ] 设计 `space_candidates.source_session_ids` 从 legacy `sessions.id` 到真实 `source_sessions.id` 的兼容迁移。

原则：

- `source_sessions` 只描述外部/真实来源会话，不替代 `sessions`。
- 不回写记忆权重。
- 初期只做来源索引和展示，不参与权重计算。
- 与 `space_candidates.source_session_ids` 的关系需要迁移设计，避免混淆当前 `sessions.id`。

### P2：候选质量治理

- [ ] 对候选项目增加批量忽略/合并 UX。
- [ ] 对自动同步类 session 做降噪规则。
- [ ] 增加候选来源摘要质量评分。
- [ ] 增加候选生成 dry-run / preview 模式。

### P3：和记忆治理联动，但保持边界

- [ ] `semantic duplicate candidate queue` 只做候选，不自动合并。
- [ ] Space 视角展示重复候选，但不在 Space Candidate 流程里改记忆权重。
- [ ] 若用户显式在 Governance 页面操作，才允许修改 `user_weight/status/pinned` 等治理字段。
