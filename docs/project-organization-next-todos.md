# 项目整理优化后续待办

更新时间：2026-07-21

## 待确认

### 1. 确认 Memo 项目整理涉及的权重规则边界

检查并确认以下权重机制是否会被 `source_sessions` / `space_candidates` / 项目整理流程影响：

- 用户手动指定记录
- 自动同步记录
- `memory_units.signal_level`
- `memory_units.user_weight`
- `memory_units.pinned`
- `feature_relations.last_session_id` / session boost 相关逻辑

确认前原则：

> 不修改记忆权重字段，不重写已有 `memo.sessions` 语义，只新增来源映射层。

---

### 2. 基于权重确认结果整理最终版项目整理优化方案

在权重边界确认后，整理最终版方案，建议维度：

- `source_sessions`：真实会话来源
- `memory_units`：摘要与知识证据
- `space_candidates`：项目候选
- `spaces`：最终治理对象

需要明确：

- Source Session 只做来源映射，不改记忆本体
- Space Candidate 只做项目整理，不改记忆权重
- 确认候选只绑定 memory / todo / source session 到 Space，不改 `signal_level` / `user_weight` / `pinned`

## 当前背景

当前实现的项目整理候选仍主要基于 Memo 内部 sessions。后续应升级为基于真实来源会话的 `source_sessions` 层，以避免把“自动同步会话”和 HanaAgent 真实会话混为一谈。
