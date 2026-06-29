# Memo 新机部署执行说明

> 从零开始，10 分钟完成 Memo 记忆系统部署。适用于公司电脑、家里电脑、任何 Windows 机器。

---

## 第一步：Clone 项目

打开 PowerShell：

```powershell
git clone https://github.com/adoublegirl-dev/memo.git E:\memo
cd E:\memo
```

> 如果 GitHub 连不上，先去 `E:\` 手动建一个 `memo` 文件夹，把项目文件解压进去。

---

## 第二步：安装依赖

```powershell
pip install -r requirements.txt
pip install "mcp>=1.0"
```

> 如果 pip 很慢，加国内镜像：`pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple`

---

## 第三步：配置环境

```powershell
copy .env.example .env
notepad .env
```

在 `.env` 里填入：

```env
OPENAI_API_KEY=sk-e9711f348c114fabb565a10c4edc499b
OPENAI_BASE_URL=https://api.deepseek.com/v1
MEMO_EXTRACTION_MODEL=deepseek-v4-flash
MEMO_EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
MEMO_DB_PATH=E:/memo/memo/data/memo.db
MEMO_LOG_LEVEL=INFO
```

---

## 第四步：首次运行验证

```powershell
# 先下载嵌入模型（约 120 MB，首次需要网络）
python -c "from memo.utils.embedding import embedding_model; print('dim:', len(embedding_model.encode('test')))"

# 基础自检
python scripts/quick_check.py
```

看到 `Phase 0 基础设施验证通过！` 即成功。

> 如果 HuggingFace 下载太慢，先设镜像：`$env:HF_ENDPOINT='https://hf-mirror.com'`

---

## 第五步：配置 Agent 接入

### 5A. HanaAgent

在 HanaAgent 设置 → MCP 中添加连接器，JSON 配置：

```json
{
  "name": "memo",
  "transport": "stdio",
  "command": "python",
  "args": ["E:/memo/scripts/run_mcp.py"]
}
```

### 5B. Claude Desktop

编辑 `%APPDATA%\Claude\claude_desktop_config.json`：

```json
{
  "mcpServers": {
    "memo": {
      "command": "python",
      "args": ["E:/memo/scripts/run_mcp.py"]
    }
  }
}
```

### 5C. 其他 MCP Agent

通用配置：指向 `E:/memo/scripts/run_mcp.py` 即可。

---

## 第六步：启动后台服务

双击 `E:\memo\start_all.bat`，自动启动：
- **看板**：浏览器打开 `http://localhost:9120`
- **自动同步守护进程**：后台监控 Agent 对话，实时记入 Memo

---

## 第七步：验证 Agent 能调 Memo

对 Agent 说：

> 帮我查看 Memo 记忆系统的统计信息

如果返回了会话数、记忆数、特征词数，说明接入成功。

---

## 日常操作速查

| 操作 | 命令 |
|------|------|
| 一键启动 | 双击 `E:\memo\start_all.bat` |
| 一键停止 | 双击 `E:\memo\stop_all.bat` |
| 查看看板 | 浏览器打开 `http://localhost:9120` |
| 完整性验证 | `python E:\memo\scripts\verify_all.py` |
| 导入历史会话 | `python E:\memo\scripts\import_sessions.py` |
| 更新代码 | `git -C E:\memo pull` |

---

## 项目结构

```
E:\memo\
├── memo/               # 核心 Python 包
├── docs/               # 文档（架构/部署/推广/测试指南）
├── scripts/            # 脚本（启动/验证/导入/看板/watcher）
├── tests/              # 测试
├── start_all.bat       # 一键启动
├── stop_all.bat        # 一键停止
├── .env.example        # 配置模板
├── CHANGELOG.md        # 版本记录
└── README.md           # 项目说明
```

---

## 注意事项

1. **API Key 安全**：`.env` 文件已在 `.gitignore` 排除，不会被 push 到 GitHub
2. **数据库备份**：复制 `E:\memo\memo\data\memo.db` 即可备份全部记忆
3. **多机同步**：家里和公司各存一份数据库，通过 git 同步代码，数据库文件手动复制
4. **更新代码**：`git pull` 后如果依赖变了，重新 `pip install -r requirements.txt`
