# Memo 新机部署执行说明

> 从零开始，10 分钟完成 Memo 记忆系统部署。适用于任何 Windows/macOS 机器。

---

## 第一步：Clone 项目

打开终端：

```bash
git clone https://github.com/adoublegirl-dev/memo.git <项目路径>
cd <项目路径>
```

> 如果 GitHub 连不上，手动建一个项目文件夹，把项目文件解压进去。

---

## 第二步：安装依赖

```bash
pip install -r requirements.txt
pip install "mcp>=1.0"
```

> pip 慢加国内镜像：`pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple`

---

## 第三步：配置环境

```bash
copy .env.example .env
# 编辑 .env 填入你的 API Key
```

在 `.env` 里填入：

```env
LLM_API_KEY=sk-your-key-here
LLM_BASE_URL=https://api.deepseek.com/v1
MEMO_EXTRACTION_MODEL=deepseek-v4-flash
MEMO_DB_PATH=data/memo.db
MEMO_LOG_LEVEL=INFO
```

---

## 第四步：首次运行验证

```bash
# 下载嵌入模型（约 120 MB，首次需联网）
python -c "from memo.utils.embedding import embedding_model; print('dim:', len(embedding_model.encode('test')))"

# 基础自检
python scripts/quick_check.py
```

看到 `Phase 0 基础设施验证通过！` 即成功。

> HuggingFace 下载慢：先设 `$env:HF_ENDPOINT='https://hf-mirror.com'`

---

## 第五步：配置 Agent 接入

> 将下面命令中的 `<项目路径>` 替换为你的 Memo 实际目录（如 `D:/Memo` 或 `/home/user/Memo`）。

### 5A. HanaAgent

在 HanaAgent 设置 → MCP 中添加连接器，JSON 配置：

```json
{
  "name": "memo",
  "transport": "stdio",
  "command": "python",
  "args": ["<项目路径>/scripts/run_mcp.py"]
}
```

### 5B. Claude Desktop

编辑 `%APPDATA%\Claude\claude_desktop_config.json`：

```json
{
  "mcpServers": {
    "memo": {
      "command": "python",
      "args": ["<项目路径>/scripts/run_mcp.py"]
    }
  }
}
```

### 5C. 其他 MCP Agent

通用配置：指向 `<项目路径>/scripts/run_mcp.py` 即可。

---

## 第六步：启动后台服务

双击 `start_all.bat`（Windows）或运行：

```bash
python scripts/memo_dashboard.py   # 看板 → http://localhost:9120
python scripts/memo_watcher.py     # 后台守护进程
```

---

## 第七步：验证 Agent 能调 Memo

对 Agent 说：

> 帮我查看 Memo 记忆系统的统计信息

如果返回了会话数、记忆数、特征词数，说明接入成功。

---

## 日常操作速查

| 操作 | 命令 |
|------|------|
| 一键启动 | 双击 `start_all.bat` |
| 一键停止 | 双击 `stop_all.bat` |
| 查看看板 | 浏览器打开 `http://localhost:9120` |
| 完整性验证 | `python scripts/verify_all.py` |
| 导入历史会话 | `python scripts/import_sessions.py` |
| 更新代码 | `git pull` |

---

## 项目结构

```
项目根目录/
├── memo/               # 核心 Python 包
├── docs/               # 文档
├── scripts/            # 脚本
├── tests/              # 测试
├── start_all.bat       # 一键启动
├── stop_all.bat        # 一键停止
├── .env.example        # 配置模板
├── CHANGELOG.md        # 版本记录
└── README.md           # 项目说明
```

---

## 注意事项

1. **API Key 安全**：`.env` 已在 `.gitignore` 排除，不会被 push
2. **数据库备份**：复制 `memo/data/memo.db` 即可备份全部记忆
3. **多机同步**：代码通过 git 同步，数据库文件手动复制
4. **更新代码**：`git pull` 后如果依赖变了，重新 `pip install -r requirements.txt`
