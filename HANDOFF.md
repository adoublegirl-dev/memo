# Memo 项目交接文档

> 2026-07-16 · V0.9-alpha · Context Space + 记忆治理 + Svelte Dashboard

---

## 一、当前定位

Memo 是一个本地私有的 AI Context Space：让不同 Agent 在正确的项目、事项和人格上下文里工作。

核心对象已经从“单条记忆”升级为：

- Memory：长期记忆单元
- Space：项目/事项/客户/产品上下文空间
- Persona：人格画像和偏好
- Todo：下一步行动与风险
- Bridge：跨 Agent 导入导出

---

## 二、当前关键路径

```text
D:\个人\Hanako项目文件\Memo_V0.1.0
├── memo/                    # Python 核心包
│   ├── core/engine.py        # 统一门面
│   ├── store/                # SQLite、记忆、图谱、向量、迁移
│   ├── space/                # Context Space 管理、识别、简报
│   ├── persona/              # 人格画像
│   ├── todo/                 # 待办
│   └── mcp/server.py         # MCP Server
├── src/                      # Svelte Dashboard 源码
├── dashboard/dist/           # Dashboard 构建产物
├── scripts/                  # 运行、升级、自检、打包脚本
├── data/memo.db              # 生产数据库（不提交 Git / 不进发布包）
├── README.md
├── CHANGELOG.md
└── HANDOFF.md
```

---

## 三、重要安全规则

1. 不要直接删除 `data/*.db`、`*.db-wal`、`*.db-shm`。
2. production migration 前必须备份；代码已有自动备份，但正式升级前建议手动复制一份。
3. 首次升级不要直接双进程 `start_all.bat`，推荐先：

```bat
python scripts\init_db.py
python scripts\doctor.py
start_all.bat
```

或运行：

```bat
upgrade.bat
```

4. 发布包必须排除 `.env`、真实数据库、日志、备份、node_modules。

---

## 四、主要功能状态

| 模块 | 状态 |
|---|---|
| 记忆写入/检索 | 可用，三通道 + RRF |
| Context Space | V0.9-alpha，已支持创建、识别、绑定、解绑、归档、简报、Space recall |
| 记忆治理 | 已加入 schema 与 Dashboard/MCP 基础操作：标重要、错误、过期、静默、软删除、恢复 |
| Dashboard | Svelte + Vite 门面已搭建，`memo_dashboard.py` 服务 dist，旧页面 fallback |
| 待办 | 支持创建、完成、重开、Space 绑定 |
| 人格 | 支持画像查看，编辑体验仍可增强 |
| Graph | 当前为入口占位，Canvas 图谱仍待做 |
| 发布工程 | 已有 doctor / build_release / PID stop / upgrade |

---

## 五、常用命令

```bat
REM 安全升级 / migration
python scripts\init_db.py

REM 只读环境检查
python scripts\doctor.py

REM 启动全部
start_all.bat

REM 停止全部
stop_all.bat

REM 测试隔离库
test.bat

REM 构建前端
npm run build

REM 安全打包
python scripts\build_release.py --include-dist
```

---

## 六、当前仍建议继续增强

1. Canvas 2D + D3-force 图谱真实渲染。
2. Space-aware graph spreading：在图扩散阶段加入 Space soft bias，而不仅仅是结果乘 1.1。
3. 自动归类待确认队列：确认归入 / 不是这个 Space / 新建 Space / 以后类似归这里。
4. Persona 断言来源弹窗、编辑、锁定、删除的新 UI。
5. 更完整的 Space 时间线、决策区、风险区、里程碑区。
6. docs/setup-guide.md、docs/deploy-guide.md、docs/testing-guide.md 仍需彻底清理乱码和旧路径。

---

## 七、发布注意

推荐使用：

```bat
npm run build
python scripts\doctor.py
python scripts\build_release.py --include-dist
```

生成的 zip 默认不会包含 `.env`、`data/*.db`、`logs/`、`node_modules/`、`data/backups/`。
