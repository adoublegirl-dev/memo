# Memo P1-P3 一口气推进记录

> 2026-07-16 · 本地实现，暂未推 GitHub

## P1：记忆治理增强

### 已完成

1. `ingestion_events`

新增迁移：

```text
memo/store/migrations/014_governance_persona_space.sql
```

新增表：

```text
ingestion_events
```

用途：记录 watcher / import / MCP 重试等输入是否已处理，避免同一段输入被多条链路重复消费。

新增模块：

```text
memo/dedupe/ingestion.py
```

能力：

- `conversation_hash()`
- `message_hash()`
- `check_ingestion()`
- `record_ingestion()`
- `recent_ingestion_events()`

`engine.remember_conversation()` 已接入 ingestion 闸门。

2. `memory_links`

新增表：

```text
memory_links
```

支持关系：

```text
MERGED_INTO
REFINE
SUPERSEDE
RELATED
```

新增能力：

```python
engine.memory_link(...)
engine.memory_links(...)
```

`MERGED_INTO` 会将 source memory 标记为 `muted`，但不会物理删除。

3. 治理概览

新增：

```python
engine.governance_overview(limit=50)
```

Dashboard API：

```text
GET  /api/governance
POST /api/memory/link
```

返回：

- dedupe records
- ingestion events
- memory links
- governed memories

---

## P2：人格系统优化

### 已完成

1. 人格断言去重 / 合并

新增 helper：

```python
_merge_or_insert_assertion()
```

规则：

```text
同一 dimension 内 embedding 相似度 >= 0.88
→ 不新增断言
→ 合并 evidences
→ 提升 confidence
→ 写 persona_audit_logs
```

接入位置：

- baseline 构建
- incremental refine 新断言

2. 人格审计

新增表：

```text
persona_audit_logs
```

记录：

- create
- merge_similar
- supersede
- edit/lock/delete 后续可继续接入

3. 人格增量成本统计

新增表：

```text
persona_update_runs
```

记录：

- new_memories
- skipped_memories
- candidate_checks
- llm_calls_estimated
- saved_calls_estimated
- top_k_assertions
- result_json

当前人格增量逻辑：

```text
新增记忆
→ 规则过滤人格相关性
→ embedding 找 top8 活跃断言
→ 仅 top8 调 LLM
→ 记录节省调用估算
```

---

## P3：Context Space 深化

### 已完成

1. Space alias / 创建前去重

`space_manager.create()` 现在会先走：

```python
find_duplicate()
```

检查：

- 同名 Space
- alias / normalized_alias
- embedding 相似度 >= 0.88

命中后返回已有 Space：

```json
{"created": false, "duplicate_reason": "..."}
```

`space_aliases` 新增：

```text
normalized_alias
```

2. Space-aware recall 增强

`engine.recall(..., space_id=...)` 调整：

- Space 检索时扩大 RRF 候选池，避免提前截断。
- `boost` 模式下当前 Space 记忆从 `1.1` 提升到 `1.25`。
- Space 内 DECISION 额外轻微加权。
- explanation 保留当前 Space 命中原因。

3. Space 简报增强

`space_summarizer.summarize()` 现在支持：

```text
brief
handoff
risk
weekly
```

新增：

```text
summary_text
```

可选持久化：

```python
engine.space_profile(space_id, mode="handoff", persist=True)
```

新增表：

```text
space_summaries
```

Dashboard API 支持：

```text
GET  /api/space/<id>?mode=handoff
POST /api/space/action { action: "summarize", mode, persist }
```

---

## 测试

新增：

```text
tests/test_p1_p3_enhancements.py
```

覆盖：

- Space alias duplicate
- memory_links MERGED_INTO
- governance overview
- space_profile handoff summary persist

已有去重/人格测试继续通过。

执行：

```bat
python -m py_compile memo/dedupe/ingestion.py memo/store/memory_store.py memo/core/engine.py memo/persona/extractor.py memo/space/manager.py memo/space/summarizer.py scripts/memo_dashboard.py
.\test.bat
```

结果：

```text
7 passed
```

---

## 仍未做 / 后续可继续精修

1. Dashboard 还没有专门的 Governance 可视化页面，只开放了 API。
2. Persona Dashboard 的 edit/lock/delete 尚未全部写 persona_audit_logs。
3. Todo 本体去重尚未接入 `todos` 表创建逻辑。
4. semantic duplicate candidate 尚未做自动 merge queue。
5. ingestion_events 已接入 `remember_conversation`，但 watcher/import 的源 metadata 还可以继续细化。
6. Space summary 当前为规则聚合文本，后续可接 LLM 生成更像周报/交接文档的版本。
7. 本地图谱修复仍保留本地，不推 GitHub。
