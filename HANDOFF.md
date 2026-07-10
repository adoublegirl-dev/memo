# Memo 项目交接文档

> 2026-07-10 · 当前版本 V0.3.0 · 数据库 55 条记忆（58 个会话文件待导入）

---

## 一、项目路径

```
D:\个人\Hanako项目文件\Memo_V0.1.0\
├── memo/              # 核心包
├── scripts/           # 运维脚本
├── docs/              # 文档 + V0.3.0/V0.4.0 优化方案
├── data/memo.db       # 数据库（3.3MB，55 条记忆）——唯一生效库
├── start_all.bat      # 一键启动
├── stop_all.bat       # 一键停止
├── AGENT_PROMPT.md    # Agent 提示词
├── SKILL.md           # Skill 定义
└── .env               # DeepSeek API Key + 配置（MEMO_DB_PATH=data/memo.db）
```

> ⚠️ **注意**：曾经短暂使用过 `memo_clean.db`，该文件已被删除。数据库统一为 `memo.db`，所有代码/文档均已同步修改。

## 二、当前状态

- **数据库**：`memo.db` = 55 条记忆（唯一生效库）
- **Dashboard**：运行中 → http://localhost:9120（可能存在多个重复实例，停止后重新启动即可）
- **MCP**：已停止
- **导入**：尚未开始，`~/.hanako/agents/hanako/sessions/` 下有 58 个 JSONL 会话文件待导入

## 三、导入历史会话

```bash
cd D:\个人\Hanako项目文件\Memo_V0.1.0
set HF_ENDPOINT=https://hf-mirror.com

# 批量导入（推荐，跳过 CAS，导入后统一跑生命周期）
python scripts/import_sessions.py --skip-cas

# 导入完成后统一跑 CAS + 生命周期
python -c "from memo.core.engine import engine; engine.init(); r=engine.run_lifecycle(); print(r)"

# 逐个导入（带 CAS，较慢）
python scripts/import_sessions.py
```

## 四、常用命令

```bash
cd D:\个人\Hanako项目文件\Memo_V0.1.0

# 启停
双击 start_all.bat          # 启动看板 + watcher
双击 stop_all.bat           # 停止所有服务

# 维护
python -c "from memo.core.engine import engine; engine.init(); engine.run_lifecycle()"

# 标记/清理测试数据
python scripts/_mark_legacy.py     # 标记当前数据
python scripts/_clean_legacy.py    # 删除标记数据

# 看板
http://localhost:9120
```

## 五、Memo Skill

已安装到 `C:\Users\PC\.hanako\skills\memo\SKILL.md`，新会话自动生效。

Agent 提示词：`D:\个人\Hanako项目文件\Memo_V0.1.0\AGENT_PROMPT.md`

## 六、V0.3.0 核心能力

| 能力 | 说明 |
|------|------|
| MVG 记忆价值门控 | 写入前 LLM 评分，<3.0 跳过闲聊 |
| CAS 变更感知 | 写入后自动检测推翻旧事实 |
| ESA 显式信号放大 | 手动「记住」L2（×1.5），自动 L0/L1 |
| SCB 会话凝聚力加成 | 同会话关联边权重加成 |
| 看板图谱 | D3.js 力导向图，绿色连线，全屏弹窗 |
| LLM 重试 | API 失败 3 次指数退避重试 |

## 七、V0.4.0 待开发

文档：`docs/V0.4.0-优化方案.md`

| 代号 | 名称 |
|:---:|------|
| DBL | 数据库生命周期管理（WAL 修复 + 强停 + 备份） |
| RMP | 导入断点续传（--resume） |
| DIM | 日常记忆入库（watcher 验证 + 手动触发 + 防重复） |
| CON | Consolidation 合并去重 |
| DKM | Dashboard 明暗切换 |

## 八、Git

本地有未推送的 commit，VPN 开着时：

```bash
cd D:\个人\Hanako项目文件\Memo_V0.1.0
git push --force
```

## 九、事故记录

**2026-07-10**：此前因 memo.db 连接问题改为使用 memo_clean.db，上午处理前端数据展示问题时删除了 WAL 文件，导致 memo_clean.db 清空（0KB，0表）。memo_clean.db 已删除，统一使用 memo.db。**此后任何涉及数据库文件/WAL/表删除等不可逆操作，必须先与用户确认。**
