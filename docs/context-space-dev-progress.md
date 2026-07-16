# Context Space 开发进度记录

> 2026-07-16 · V0.9-alpha 后端闭环 + Dashboard P0 门面重构

## 已完成

### Phase 0：安全底座

- `MEMO_ENV=production/development/test`
  - production：沿用 `MEMO_DB_PATH` 或 `data/memo.db`
  - development：`data/memo_dev.db`
  - test：`data/memo_test.db`
- 迁移前 production 自动备份数据库到 `data/backups/memo-before-migration-*.db`
- 新增 `tests/conftest.py`，pytest 强制走 test DB，并在结束后清理 `memo_test.db*`
- 新增 `test.bat`
- `.gitignore` 增加 dev/test/backups/node_modules 忽略项

### Phase 1：Space Schema

新增 migration：

- `006_spaces.sql`
- `007_sessions_space.sql`
- `008_todos_space.sql`
- `009_space_memories.sql`
- `010_space_aliases.sql`

新增表/字段：

- `spaces`
- `space_aliases`
- `space_memories`
- `sessions.space_id`
- `todos.space_id`
- `todos.space_relation_type`

默认创建 `Inbox / 未归档` 空间，但不强制回填旧数据。

### Phase 2：后端基础闭环

新增模块：

- `memo/space/__init__.py`
- `memo/space/manager.py`
- `memo/space/detector.py`
- `memo/space/summarizer.py`

Engine 新增：

- `space_create`
- `space_list`
- `space_get`
- `space_update`
- `space_detect`
- `space_bind_memory`
- `space_profile`
- `space_recall`

增强：

- `start_session(..., space_id=None)`
- `remember(..., space_id=None)`
- `remember_conversation(..., space_id=None)`
- `recall(..., space_id=None, space_mode='boost')`
- `todo_add/list/search(..., space_id='')`

MCP 新增工具：

- `space_create`
- `space_list`
- `space_activate`
- `space_deactivate`
- `space_profile`
- `space_recall`
- `space_detect`

Dashboard API 新增：

- `GET /api/spaces`
- `GET /api/space/<id>`
- `POST /api/space/action`

### Phase 3：Dashboard P0 门面重构

新增 Svelte + Vite 前端：

- `package.json`
- `vite.config.js`
- `index.html`
- `src/`
- `dashboard/dist/`

已实现页面：

- 总览 `/`
- 图谱 `/graph`（目前为门面占位，Canvas 图谱下一阶段接）
- 记忆 `/memories`
- 上下文空间 `/spaces`
- 人格 `/persona`
- 待办 `/todos`

已实现视觉基础：

- 暖白/石墨暗色双主题 token
- 简约卡片、badge、列表、按钮、输入框
- Lucide SVG 图标（`@lucide/svelte`）
- 页面入场、hover、骨架屏等基础动效
- Space 创建和 Space Profile 展示

`scripts/memo_dashboard.py` 已支持：

- 优先服务 `dashboard/dist/index.html`
- 服务 Vite 构建后的 `/assets/*`
- 保留旧内嵌 PAGE 作为 fallback
- API 与静态前端共存

## 验证结果

执行：

```bat
.\test.bat
npm run build
```

结果：

```text
3 passed
vite build success
```

额外验证：

- `python -m py_compile scripts/memo_dashboard.py`
- 临时 HTTPServer 验证 `/`、`/assets/index-*.css`、`/api/spaces` 均返回 200

已确认测试库清理正常，`E:\memo\data` 下只保留：

- `memo.db`
- `backups/`

未生成持久 `memo_test.db`。

## 尚未完成

### 前端 P1

- Canvas 2D + D3-force 图谱重写
- 全局搜索 Command Palette
- Persona 雷达图
- Space 时间线 / 激活路径小图谱
- 更完整的 Space 编辑、归档、绑定 UI

### 检索增强第二阶段

当前 Space 检索实现为：

- `within`：只返回 `space_memories` 内记忆
- `boost`：空间内结果 × 1.1

尚未改造图扩散 BFS 的 Space-aware propagation，也未接入 centroid secondary score。

### 生产库迁移

尚未主动在 production `data/memo.db` 上执行新迁移。

首次生产启动时会检测 pending migrations，并先自动备份数据库。建议正式切换前手动备份一次。

## 注意事项

- 目前 Space 作为软边界，不切断全局记忆图谱。
- `feature_tags` / `feature_relations` 继续全局共享。
- 旧数据不强制归类，避免污染。
- 低置信自动检测暂不创建新 Space。
- Space 自动绑定阈值当前为 `confidence >= 0.8`。
