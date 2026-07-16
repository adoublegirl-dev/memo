# Memo 安装配置指南

## 1. 环境要求

- Python 3.11+
- pip
- 可选：Node.js + npm（仅在需要重新构建 Dashboard 时）

## 2. 安装依赖

```bat
pip install -r requirements.txt
```

## 3. 配置环境变量

复制 `.env.example` 为 `.env`：

```env
LLM_API_KEY=sk-your-key-here
LLM_BASE_URL=https://api.deepseek.com/v1
MEMO_EXTRACTION_MODEL=deepseek-v4-flash
MEMO_GATING_MODEL=deepseek-v4-flash
MEMO_EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
MEMO_DB_PATH=data/memo.db
MEMO_LOG_LEVEL=INFO
```

说明：

- 生产库默认是 `data/memo.db`。
- `.env` 不要提交 Git，也不要放进发布包。
- development/test 会自动使用隔离库：`data/memo_dev.db` / `data/memo_test.db`。

## 4. 初始化 / 升级数据库

```bat
python scripts\init_db.py
```

该命令默认只执行初始化与 migration，不写入测试数据。

写入自检请使用测试环境：

```bat
set MEMO_ENV=test
python scripts\init_db.py --self-test
```

## 5. 启动

```bat
start_all.bat
```

访问：

```text
http://localhost:9120
```

## 6. 停止

```bat
stop_all.bat
```

## 7. 自检

```bat
python scripts\doctor.py
```
