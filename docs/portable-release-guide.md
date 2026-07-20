# Memo Portable Release 指南

Memo 的主线交付形态是 **zip 解压即用**。Docker 只作为未来可选部署方式，当前 P4 不启用 Docker，不改变现有运行方式。

## 运行方式

Windows 本地默认入口保持不变：

```bat
start_all.bat
stop_all.bat
upgrade.bat
```

Dashboard 默认：

```text
http://localhost:9120
```

## 发布包构建

构建前建议先执行：

```bat
python scripts\doctor.py
npm run build
.\test.bat
```

生成普通 zip：

```bat
python scripts\build_release.py --include-dist
```

生成给非研发同事使用的 Windows 便携 zip，可在已经准备好 `.venv` 后加入运行环境，避免对方现场下载大量依赖：

```bat
python scripts\build_release.py --include-dist --include-venv
```

注意：`--include-venv` 只适合同系统/同架构分发，例如 Windows x64 发给 Windows x64。包会明显变大。

发布包默认排除：

- `.env`
- 真实数据库：`data/*.db`、`memo/data/*`
- 数据库备份：`data/backups/*`
- PID：`data/pids/*`
- 日志：`*.log`、`logs/*`
- `node_modules/*`
- `.venv/*`（除非显式 `--include-venv`）
- `install_output/*`
- `.git/*`
- 本地 scratch 脚本：`scripts/_*.json`、`scripts/_check_*.py`

## 数据迁移原则

真实用户数据不放进发布包。迁移到新机器时单独备份/复制：

```text
memo/data/memo.db
或 .env 中 MEMO_DB_PATH 指向的数据库
```

升级前先备份数据库，生产 migration 会自动创建备份，但重要数据建议人工再复制一份。

## Docker 策略

当前不启用 Docker。后续如果需要部署到小主机、NAS、VPS，可额外增加 Dockerfile / docker-compose.yml，但不得替代 zip + bat 的主线运行方式。
