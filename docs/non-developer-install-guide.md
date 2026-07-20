# Memo 给同事使用的安装说明

这份说明面向**不写代码、不熟悉 Python、不想手改配置文件**的同事。

你只需要知道三件事：

1. Memo 是一个本地记忆系统。
2. 安装完成后，你的 AI Agent 可以通过 Memo 记住长期上下文。
3. 正常情况下，只需要双击脚本，不需要自己写 MCP 配置。

---

## 一、你需要准备什么

### 必须准备

- 一台 Windows 电脑
- Memo 项目压缩包或项目文件夹
- 一个可用的 LLM API Key，例如 DeepSeek Key
- Python 3.11 或更高版本

### 如果没有 Python

先安装 Python：

```text
https://www.python.org/downloads/
```

安装时建议勾选：

```text
Add python.exe to PATH
```

如果你看不懂这句话，没关系，安装失败时把截图发给维护者。

---

## 二、最快安装方式

进入 Memo 文件夹，双击：

```text
install.bat
```

安装器会自动做这些事：

```text
1. 检查 Python
2. 创建独立运行环境 .venv
3. 安装 Memo 需要的依赖
4. 创建 .env 配置文件
5. 初始化数据库
6. 生成 Agent 所需的 MCP 配置
7. 安装 Skill 或生成可复制配置
8. 执行安装后自检
```

安装过程中如果问你是否使用镜像，国内网络建议选：

```text
是 / Y
```

这样下载依赖会更稳定。

---

## 三、填写 API Key

如果安装器没有让你填写 Key，安装后打开 Memo 文件夹里的：

```text
.env
```

找到这一行：

```text
LLM_API_KEY=sk-your-key-here
```

改成你的真实 Key：

```text
LLM_API_KEY=sk-xxxxxxxxxxxxxxxx
```

保存文件。

> 注意：不要把 `.env` 发给别人，因为里面有你的 Key。

---

## 四、启动 Memo

双击：

```text
start_all.bat
```

正常情况下，浏览器会打开：

```text
http://localhost:9120
```

如果没有自动打开，可以手动复制这个地址到浏览器。

停止服务时双击：

```text
stop_all.bat
```

---

## 五、配置你的 Agent

### 方式 A：HanaAgent

安装器会自动复制 Memo Skill 到 HanaAgent 的 skills 目录。

如果 MCP 没有自动出现，请打开：

```text
install_output/hanaagent_mcp_ready_to_paste.json
```

然后在 HanaAgent：

```text
设置 → MCP 连接器 → 添加 MCP 服务器
```

把里面的配置复制进去。

完成后重启 HanaAgent。

---

### 方式 B：WorkBuddy

安装器会自动写入：

```text
~/.workbuddy/mcp.json
```

并自动复制 Memo Skill。

完成后重启 WorkBuddy。

---

### 方式 C：Claude Desktop

安装器会自动写入 Claude Desktop 的配置文件。

完成后重启 Claude Desktop。

---

### 方式 D：Cursor

安装器会在当前 Memo 项目里生成：

```text
.cursor/mcp.json
```

如果你要在别的项目里用 Cursor，请把 `install_output/memo_mcp_config.generated.json` 里的配置复制到目标项目的 `.cursor/mcp.json`。

---

## 六、如果只想重新配置 Agent

如果依赖已经安装过，只是 Agent 配置错了，双击：

```text
install_agent.bat
```

它会重新生成 MCP 配置，并尽量自动写入对应 Agent。

不会删除你的数据库。

---

## 七、如何判断安装成功

### 看板成功

浏览器能打开：

```text
http://localhost:9120
```

并看到 Memo 页面。

### Agent 成功

在 Agent 里能看到 Memo MCP 工具，例如：

```text
memo_recall
memo_remember
memo_stats
persona_ask
todo_add
space_list
```

### 自检成功

也可以手动运行：

```text
.venv\Scripts\python.exe scripts\smoke_test_mcp.py
```

看到：

```text
结果：通过
```

就说明基本安装成功。

---

## 八、常见问题

### 1. 安装很久不动

多数情况是在下载 Python 依赖或嵌入模型。

国内网络建议重新运行：

```text
install.bat
```

当它问是否使用镜像时，选择：

```text
是 / Y
```

---

### 2. 出现 torch / c10.dll / WinError 1114

如果报错里有类似：

```text
Error loading torch\\lib\\c10.dll
WinError 1114
```

这通常是 Windows 上 PyTorch 动态库加载失败。新版安装包已经固定了更稳的 PyTorch 版本。处理方式：

```text
1. 关闭安装窗口
2. 重新运行新版 install.bat
3. 如果仍然失败，安装 Microsoft Visual C++ Redistributable 2015-2022 x64
4. 重启电脑
5. 再运行 install.bat
```

安装器会先生成 `install_output`，所以即使数据库初始化失败，也应该能找到 HanaAgent 的 MCP 配置文件。

---

### 3. Agent 找不到 Memo

优先做三件事：

```text
1. 重新运行 install_agent.bat
2. 重启 Agent
3. 检查 MCP 配置里是不是绝对路径
```

正确配置应该类似：

```json
{
  "command": "D:/Memo/.venv/Scripts/python.exe",
  "args": ["D:/Memo/scripts/run_mcp.py"],
  "env": {
    "MEMO_DB_PATH": "D:/Memo/data/memo.db",
    "MEMO_ENV": "production"
  }
}
```

重点是：

```text
路径必须是你电脑上真实存在的路径
```

---

### 4. 启动 Memo 后页面一直停在加载动画

这通常说明 Dashboard 后端没有启动成功。

先双击：

```text
stop_all.bat
```

然后重新运行：

```text
install.bat
```

再双击：

```text
start_all.bat
```

新版 `start_all.bat` 会优先使用 Memo 文件夹里的 `.venv`，避免服务启动时误用系统 Python。

---

### 5. 启动 Memo 后页面打不开

先双击：

```text
stop_all.bat
```

再双击：

```text
start_all.bat
```

如果还是打不开，把窗口截图发给维护者。

---

### 6. API Key 错了怎么办

打开：

```text
.env
```

修改：

```text
LLM_API_KEY=你的新 Key
```

保存后重新启动 Memo。

---

### 7. 会不会删掉我的数据

正常安装不会删除数据库。

你的主要数据在：

```text
data/memo.db
```

升级或迁移前，可以手动复制这个文件做备份。

---

## 九、给维护者看的说明

本安装方案的原则：

```text
1. 不改核心记忆逻辑
2. 不改数据库 schema
3. 不强依赖 Docker
4. 所有 Agent 配置使用绝对路径
5. 写入已有配置前自动备份
6. HanaAgent MCP 连接器不强行写内部配置，只生成 ready-to-paste 文件
7. install.bat 面向首次安装
8. install_agent.bat 面向 Agent 配置修复
9. smoke_test_mcp.py 只读/轻量，不写记忆，不调用 LLM
```

---

## 十、推荐给同事的话术

你可以直接这样告诉同事：

```text
解压 Memo 后，先双击 install.bat。
安装完成后，把 .env 里的 LLM_API_KEY 改成你的 Key。
然后双击 start_all.bat。
如果你用 HanaAgent，按 install_output/hanaagent_mcp_ready_to_paste.json 里的配置添加 MCP。
遇到问题直接截图发我，不用自己改代码。
```
