# Memo 部署指南

## 1. 推荐部署流程

```bat
cd D:\Memo
pip install -r requirements.txt
copy .env.example .env
notepad .env
python scripts\init_db.py
python scripts\doctor.py
start_all.bat
```

## 2. 生产升级流程

首次从旧版本升级到包含新 migration 的版本时，不建议直接双进程启动。

推荐：

```bat
stop_all.bat
python scripts\init_db.py
python scripts\doctor.py
start_all.bat
```

也可以使用：

```bat
upgrade.bat
```

## 3. 数据库与备份

- 生产数据库：`data/memo.db`
- 生产 migration 前会自动备份到 `data/backups/`
- 正式升级前仍建议手动复制一份：

```text
data/memo.db -> data/backups/memo-manual-before-upgrade.db
```

## 4. Dashboard

默认访问：

```text
http://localhost:9120
```

如需重新构建前端：

```bat
npm install
npm run build
```

`memo_dashboard.py` 会优先服务 `dashboard/dist`，若不存在则回退旧内嵌页面。

## 5. 安全打包

```bat
python scripts\build_release.py --include-dist
```

默认排除：

- `.env`
- `data/*.db`
- `data/*.db-wal`
- `data/*.db-shm`
- `data/backups/`
- `logs/`
- `node_modules/`
- dev/test 数据库

## 6. MCP 接入

```json
{
  "mcpServers": {
    "memo": {
      "command": "python",
      "args": ["<项目路径>/scripts/run_mcp.py"],
      "env": {
        "MEMO_DB_PATH": "<项目路径>/data/memo.db"
      }
    }
  }
}
```
