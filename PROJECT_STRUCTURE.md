# Memo 项目结构说明

本仓库同时包含 **应用代码** 与 **打包安装器**，两者是「开发 → 发布」的上下游关系。

## 目录结构

| 目录 | 角色 | 说明 |
|------|------|------|
| `memo/` | 应用代码 | Memo 后端（Python：记忆 / 空间 / 人格 / 待办核心逻辑） |
| `src/` | 应用代码 | 前端 Dashboard（Svelte） |
| `desktop/` | 应用代码 | Memo Desktop Companion（Electron 桌面伴侣） |
| `feedback_service/` | 应用代码 | 反馈服务 |
| `website/` | 应用代码 | 官网静态文件与部署脚本 |
| `scripts/` | 应用代码 | 应用侧运维 / 数据脚本 |
| `tests/` | 应用代码 | 应用侧测试 |
| `docs/` | 文档 | 设计与执行文档 |
| **`packaging/`** | **打包工程** | **把应用代码 + runtime + models 打包成 Windows 安装包** |
| `data/` | 运行时数据 | 用户记忆库（**不进 git**） |
| `config/` | 运行时配置 | 用户配置（**不进 git**） |

## 两个工程的关系

```
应用代码（根目录各业务目录：memo/ src/ desktop/ website/ ...）
        │
        │  被打包
        ▼
packaging/（安装器工程：installer/ scripts/ tests/）
        │
        │  产出
        ▼
Memo Setup x.x.x.exe / Memo Lite Setup x.x.x.exe / 增量更新包
        │
        │  上传
        ▼
官网服务器（memo.zhaguzhagu.com/downloads/）
```

## 日常工作分工

| 场景 | 只改哪里 |
|------|---------|
| 开发功能 / 修 bug | 根目录应用代码（`memo/`、`src/`、`desktop/` 等） |
| 调整安装流程 / 打包配置 | `packaging/`（`installer/`、`scripts/`、`*.json`） |
| 发版 | 打 git tag（同时标记应用版本与打包版本）+ 在 `packaging/` 跑构建脚本 |

**版本号同源**：应用代码与打包工程在同一个仓库、同一个 tag 下，不会出现"包版本对不上代码版本"的问题。

## 不进 git 的内容

| 内容 | 原因 |
|------|------|
| `data/`、`config/` | 用户数据与配置 |
| `runtime/`、`models/`、`node_modules/` | 二进制约 2.5 GB，可重新生成 |
| `build*/`、`artifacts/` 里的 .exe | 打包产物，上传服务器后不留在仓库 |
| `.env`、任何密钥 | 安全 |

## 历史

- 2026-11-20：`packaging/` 原为独立的本地仓库 `Memo_Installer`（8 个提交、无远程备份），合并进本仓库统一管理，避免打包器源码与应用代码版本脱节。
