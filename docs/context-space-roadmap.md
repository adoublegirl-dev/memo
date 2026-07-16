# Memo Context Space 详细待办与路线图

> 2026-07-16 · 同步 GitHub 用 · V0.9-alpha

## 一、已完成基线

### 1. 安全底座

- [x] `MEMO_ENV=production/development/test`
- [x] development/test 独立数据库，避免污染 `data/memo.db`
- [x] production 有待执行 migration 时自动备份
- [x] pytest 强制使用 `data/memo_test.db`
- [x] `test.bat` 一键测试
- [x] `.gitignore` 忽略 dev/test DB、backups、node_modules

### 2. Context Space 后端

- [x] 新增 `spaces`
- [x] 新增 `space_aliases`
- [x] 新增 `space_memories`
- [x] `sessions.space_id`
- [x] `todos.space_id`
- [x] 默认 `Inbox / 未归档`
- [x] `memo/space/manager.py`
- [x] `memo/space/detector.py`
- [x] `memo/space/summarizer.py`
- [x] Engine `space_*` 门面接口
- [x] MCP `space_*` 工具
- [x] Dashboard Space API
- [x] Space 基础测试

### 3. Dashboard P0 门面

- [x] Svelte + Vite 项目骨架
- [x] 暖白 / 暗色主题 tokens
- [x] Lucide 图标体系
- [x] Shell / Sidebar / TopBar
- [x] Overview 页面
- [x] Memories 页面
- [x] Spaces 页面
- [x] Persona 页面
- [x] Todos 页面
- [x] Graph 占位页
- [x] `memo_dashboard.py` 优先服务 `dashboard/dist`
- [x] `npm run build` 通过
- [x] `.\test.bat` 通过

---

## 二、P1 待办：前端体验增强

### 1. Canvas 图谱重写

- [ ] 用 Canvas 2D 替换当前 SVG/D3 DOM 图谱
- [ ] 保留 D3-force 作为布局计算层
- [ ] 实现缩放、拖拽、hover hit-test
- [ ] 节点 hover 高亮一度/二度关联
- [ ] 非关联节点淡出
- [ ] 节点详情侧栏
- [ ] 图谱加载扩散动画
- [ ] 大图谱性能测试，目标 1000 节点可用

### 2. Space 页面增强

- [ ] Space 编辑表单
- [ ] Space 归档 / 恢复
- [ ] Space alias 管理
- [ ] 手动绑定记忆到 Space
- [ ] 手动解绑记忆
- [ ] Space 待办创建入口
- [ ] Space 时间线
- [ ] Space 风险 / 决策 / 里程碑分区
- [ ] 管理型 Space profile 模板 UI

### 3. 全局搜索

- [ ] Command Palette 快捷入口
- [ ] 搜索记忆、Space、待办、人格断言
- [ ] 支持键盘选择
- [ ] 支持跳转到对应页面

### 4. Persona 可视化

- [ ] 人格雷达图
- [ ] 维度置信度统计
- [ ] 断言来源记忆弹窗
- [ ] 断言编辑 / 锁定 / 删除的新 UI

---

## 三、P2 待办：Space 检索增强

### 1. Space-aware recall

- [ ] 在 graph spreading 阶段加入 Space boost
- [ ] 当前 Space 内特征传播系数加权
- [ ] 非当前 Space 不硬过滤，只保持 soft bias
- [ ] centroid_embedding secondary score
- [ ] Space 内 recall 解释信息：为什么命中

### 2. 自动归类增强

- [ ] detector 加入 tag 覆盖率
- [ ] detector 加入 recent active Space 加权
- [ ] detector 加入 LLM fallback
- [ ] 0.5~0.8 置信度候选进入待确认队列
- [ ] 低置信不自动创建 Space

### 3. Space Summarizer

- [ ] LLM 生成 Space 200 字简报
- [ ] weekly summary
- [ ] handoff summary
- [ ] risk summary
- [ ] decision summary

---

## 四、P3 待办：记忆治理

- [ ] `memory_units.status`
- [ ] `memory_units.user_weight`
- [ ] `memory_units.pinned`
- [ ] `memory_audit_logs`
- [ ] Dashboard 记忆编辑
- [ ] 标记重要
- [ ] 标记错误
- [ ] 标记过期
- [ ] 软删除
- [ ] 检索解释
- [ ] 用户反馈影响排序

---

## 五、P4 待办：发布与交付

- [ ] `scripts/doctor.py` 环境检查
- [ ] `scripts/build_release.py` 安全打包
- [ ] README 更新 Context Space 说明
- [ ] README 更新 Dashboard 构建说明
- [ ] docs/setup-guide.md 修复乱码和旧路径
- [ ] docs/deploy-guide.md 修复乱码和旧路径
- [ ] docs/testing-guide.md 修复乱码和旧路径
- [ ] GitHub Release 打包规则
- [ ] 明确是否提交 `dashboard/dist`

---

## 六、生产迁移注意事项

1. 当前代码尚未主动对 production `data/memo.db` 执行 006-010 migration。
2. 首次 production 启动时会自动检测 pending migrations，并先备份主库。
3. 正式切换前建议人工复制一次：

```text
data/memo.db -> data/backups/memo-manual-before-v090.db
```

4. 旧数据不会强制归类到 Space。
5. `feature_tags` / `feature_relations` 仍全局共享。
6. Space 是软边界，不切断跨域联想。
