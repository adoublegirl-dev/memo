# Memo Desktop Companion v0.1 方案

更新时间：2026-07-22

## 1. 定位

Memo Desktop Companion 是 Memo 的桌面常驻触达层，不替代 PC Dashboard。

它负责：

- 把待办、风险、项目候选、新增记忆等信息推到用户面前
- 提供常驻系统托盘入口
- 提供一个轻量、美观、低打扰的小浮窗
- 后续扩展为简单对话入口，用于查询项目、历史记忆和今日待办

核心原则：

> Dashboard 是主工作台，Desktop Companion 是提醒与快捷入口。

## 2. 技术路线

首版采用 Electron。

选择原因：

- UI 表现力强，普通用户第一印象更好
- 可复用 Web 技术栈，开发速度快
- 支持系统托盘、原生通知、悬浮窗口、快捷键
- 后续可逐步扩展为轻量对话窗口

暂不采用：

- Python 托盘：轻量但 UI 表现弱
- Tauri：轻量但当前构建链和开发成本更高
- WinUI/.NET：后续资源占用确实成为问题时再考虑迁移

## 3. v0.1 功能范围

### 3.1 系统托盘

托盘菜单：

- 打开 Memo Dashboard
- 显示/隐藏桌面助手
- 刷新状态
- 暂停提醒 1 小时
- 退出桌面助手

### 3.2 桌面小浮窗

默认右下角显示，可关闭。

展示：

- Memo 服务状态
- 今日待办数量
- 风险待办数量
- 项目候选数量
- 最近记忆数量

点击相关卡片可打开 Dashboard 对应页面。

### 3.3 通知提醒

首版只做低频提醒：

- 风险待办数量变化
- 今日待办数量变化
- 项目候选数量变化
- Memo 服务不可用

默认轮询间隔：60 秒。

### 3.4 服务检测

通过本地接口检测：

- `http://127.0.0.1:9121/api/health`
- `http://127.0.0.1:9121/api/todos`
- `http://127.0.0.1:9121/api/space/candidates`
- `http://127.0.0.1:9121/api/memories`

若服务不可用：

- 显示“Memo 未启动”
- 提供打开 Dashboard / 稍后重试入口
- 后续可加“一键启动 start_all.bat”

## 4. v0.1 不做的事情

- 不做复杂桌宠动画
- 不做 Live2D / WebGL 常驻渲染
- 不做完整聊天 Agent
- 不做安装包
- 不改现有 Dashboard 主流程
- 不读取 `.env`、数据库文件或账号信息

## 5. 后续演进

### v0.2

- 快捷键呼出
- 快速新建待办
- 快速记录记忆
- 通知偏好设置

### v0.3

- 简单对话入口：查询待办、Space、历史记忆
- 项目候选快速确认入口
- 记忆治理提醒

### v1.0

- 打包安装
- 开机自启
- 主题与角色形象
- 资源占用监控
- 如资源压力过高，评估迁移 WinUI/.NET

## 6. 资源控制原则

Electron 首版按以下原则控制资源：

- 常驻窗口使用静态 DOM + CSS，避免高频动画
- 不常驻 WebGL / Canvas 动画
- 轮询间隔默认 60 秒
- 窗口隐藏时暂停 UI 刷新，只保留状态轮询
- 通知去重，避免频繁打扰

预期资源：

- 空闲托盘 + 小窗：约 100MB ~ 250MB 内存
- CPU 空闲接近 0% ~ 2%

## 7. 当前实现目标

本轮先实现可运行原型：

```bash
npm run desktop:dev
```

能看到：

- 系统托盘
- 右下角 Memo Companion 小窗
- 服务状态与统计卡片
- 点击打开 Dashboard
- 基础通知能力

## 8. Launcher 与 exe 化

Desktop Companion 同时承担 Memo Launcher 职责：

- 启动时检测 Dashboard API 是否可用
- 服务不可用时尝试拉起 `start_all.bat`
- 窗口内提供启动、停止、重启服务按钮
- 托盘菜单提供服务控制入口
- 用户可在窗口内主动开启“开机自动启动助手”

打包命令：

```bash
npm run desktop:pack   # 生成 unpacked 桌面应用目录
npm run desktop:dist   # 生成 Windows 安装包和 portable exe
```

打包安全规则：

- 不包含 `.env`
- 不包含 `data/`
- 不包含 `logs/`
- 不包含数据库、备份、用户账号信息

安装辅助脚本：

```text
desktop_install.bat
```

后续 `install.bat` / Agent 安装器可增加可选步骤：

```text
是否安装 Memo Desktop Companion？
是否创建桌面快捷方式？
是否由用户主动开启开机自启？
```
