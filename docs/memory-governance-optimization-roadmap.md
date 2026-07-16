# Memo 记忆治理优化思路：去重、人格增量与长期壁垒

> 2026-07-16 · 本地实现后整理

## 背景

一次测试待办创建后出现多条相似记忆，暴露了 Memo 当前入库链路的核心问题：

- 同一事件可能被 `todo_add`、主动 `memo_remember`、自动会话同步、watcher/import 等多条链路重复写入。
- 重复记忆会污染检索、图谱、人格画像和 token 成本。
- 结构化数据已经有自己的事实源，普通记忆不应该一股脑记录所有操作确认。

这类问题不只存在于 todo，也存在于 Space、Persona、Feature Tags、历史导入、会话同步和普通 memory_units。

---

## 已实施的第一阶段

### 1. 新增去重基础设施

新增模块：

```text
memo/dedupe/
  __init__.py
  normalizer.py
  detector.py
```

职责：

- 去除 `<mood>`、工具噪声、模板话术、格式差异。
- 生成 raw hash、normalized hash、fact key、action key、entity key。
- 入库前检测 exact duplicate 和 structured action duplicate。
- LLM 提取后检测 near fact duplicate 和 title-summary duplicate。

新增迁移：

```text
memo/store/migrations/013_memory_dedupe.sql
```

新增表：

```text
memory_dedupe_records
```

核心字段：

```text
memory_id
session_id
source_agent
raw_hash
normalized_hash
fact_key
action_key
entity_key
decision
reason
created_at
```

### 2. 写入链路增加去重闸门

`engine.remember_conversation()` 增加两道闸：

```text
Step -1：LLM 提取前
  exact normalized hash duplicate
  structured action duplicate

Step 1.5：LLM 提取后
  fact key duplicate
  title-summary duplicate
```

命中后返回：

```text
memory_id = None
extraction_method = dedupe_skipped
dedupe_result.reason = xxx
```

这样可以避免重复调用 LLM，也避免重复写 memory_units。

### 3. 手动记忆记录指纹但不自动跳过

`engine.remember()` 属于显式手动记忆，第一阶段不自动跳过，避免误杀用户主动要求记住的内容。

但会记录 dedupe fingerprint，为后续自动链路提供参考。

### 4. 人格增量更新优化

原逻辑：

```text
新增记忆 × 所有活跃人格断言 → 全部调用 LLM 判断
```

新逻辑：

```text
新增记忆
→ 规则判断是否人格相关
→ 本地 embedding 取 top8 相关断言
→ 只对 top8 候选调用 LLM
```

跳过：

- 测试类
- 纯操作类
- 构建/拉取/验证类
- 低 signal EVENT
- 无偏好/决策/情绪/价值观信号的记忆

返回结果新增：

```text
skipped_memories
candidate_checks
top_k_assertions
```

---

## 当前规则矩阵

| 数据类型 | 去重依据 | 当前处理 |
|---|---|---|
| exact memory | normalized_hash | 直接 skip |
| structured action | action_key + 10 分钟窗口 | skip |
| near fact | fact_key + 10 分钟窗口 | skip |
| title-summary | title + summary hash + 10 分钟窗口 | skip |
| manual memory | fingerprint only | 不跳过 |
| persona incremental | relevance rules + top8 assertions | 降低 LLM 调用 |

---

## 后续优化方向

### P1：结构化数据源优先

结构化事实应该由结构化表承载：

- todo → `todos`
- Space → `spaces`
- Persona → `persona_assertions`
- Memory Governance → `memory_audit_logs`

普通记忆只记录长期有价值的信息：

- 决策
- 偏好
- 项目进展
- 关键事实
- 经验教训

建议下一步增加：

```text
structured_action_policy
```

规则：

```text
todo_add / todo_close / space_activate 等操作类事件默认不写普通记忆。
除非 explicit_remember=true 或 signal_level >= 1。
```

### P2：语义近重复合并

当前第一阶段只做保守 skip，没有做自动 merge。

后续可以增加：

```text
semantic_duplicate_threshold = 0.92
semantic_refine_threshold = 0.78 ~ 0.92
```

处理方式：

```text
duplicate → skip
same_fact_more_detail → merge summary_detail / evidence
same_topic_new_detail → REFINE / MERGED_INTO
opposite_fact → supersede candidate
```

### P3：Todo 本体去重

todo 表本身也需要防重复。

规则建议：

```text
title_normalized similarity
due_date same or close
priority same
status not done
space_id same or empty
```

处理：

```text
> 0.92：直接返回 existing todo
0.75~0.92：进入 duplicate_candidates 或提示确认
< 0.75：正常创建
```

### P4：Space / FeatureTag / Persona 统一 alias 与 canonical

重复不仅发生在记忆，也发生在实体层：

```text
GitHub / github / Github / GitHub仓库
Memo / Memo项目 / 长期记忆系统
```

建议：

- `feature_tag_aliases`
- `space_aliases` 已有，继续增强
- `canonical_name`
- 中英文符号统一
- 大小写统一
- 常见技术词保护

### P5：导入链路 ingestion_events

历史导入和 watcher 最容易重复。

建议新增：

```text
ingestion_events
```

字段：

```text
source_type
source_agent
source_session_id
source_message_hash
conversation_hash
processed_memory_id
status
created_at
```

用于回答：

```text
这段输入是否处理过？
由哪条链路处理？
处理成了哪条 memory？
是否被跳过？
```

### P6：Dashboard 治理可视化

做成产品壁垒：

- 重复候选
- 被跳过的记忆
- 合并链
- 人格增量跳过原因
- LLM 调用节省统计
- 哪些结构化动作没有写普通记忆

核心卖点可以是：

> Memo 不只是会记住，更知道什么不该记。

---

## 验证结果

新增测试：

```text
tests/test_dedupe_and_persona_incremental.py
```

覆盖：

- 相同 conversation 第二次写入被 `exact_normalized_duplicate` 跳过。
- 纯操作/测试类记忆不触发人格增量 LLM。

执行：

```bat
.\test.bat
```

结果：

```text
6 passed
```

数据安全检查：

```text
项目 data 目录下无 memo_test.db 残留
```

---

## 当前未推送状态说明

本地存在图谱展示修复，不推 GitHub，按用户要求保留本地效果。

本次去重与人格增量优化也是本地改造。是否推送 GitHub 待用户后续确认。
