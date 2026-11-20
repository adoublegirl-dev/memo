# Memo 打包工程（Packaging）

本目录负责把**仓库根目录的应用代码**打包成 Windows 安装包。

## 与主仓库的关系

| 环节 | 内容 |
|------|------|
| **上游（输入）** | 仓库根目录的应用代码（`memo/`、`src/`、`desktop/`、`website/`）+ 外部依赖（`runtime/`、`models/`） |
| **本目录（处理）** | `installer/`（NSIS 安装器 + Electron 引导）、`scripts/`（构建脚本）、`tests/`（打包测试） |
| **下游（输出）** | `Memo Setup x.x.x.exe`、`Memo Lite Setup x.x.x.exe`、`Memo-Service-x.x.x.zip`（增量更新包） |

产物上传到官网服务器 `memo.zhaguzhagu.com/downloads/`，仓库内不保存 .exe。

## 主要文件

| 路径 | 作用 |
|------|------|
| `installer/installer_runner.py` | 安装主流程 |
| `installer/install_contract.py` | 安装契约（路径规则） |
| `installer/installer.nsh` | NSIS 安装脚本 |
| `installer/first_run_wizard.*` | 首次运行向导 |
| `installer/launcher.*` | 安装器启动界面 |
| `installer/path_contract.cjs` | 路径契约（JS 侧） |
| `installer/service_patch_runner.py` | 服务增量更新执行 |
| `installer/update-planner.cjs` / `update-signature.cjs` / `version-utils.cjs` | 更新规划与签名校验 |
| `scripts/build_payload.py` | 构建 payload |
| `scripts/build_release_manifest.py` | 生成签名发布清单 |
| `scripts/build_delta_patch.py` | 生成增量补丁 |
| `scripts/build_bootstrap_runtime.py` | 构建引导运行时 |
| `scripts/build_offline_assets.py` | 构建离线资源 |
| `scripts/build_model.py` | 准备嵌入模型 |
| `scripts/audit_payload.py` | 审计 payload 内容 |
| `electron-builder.lite.json` | Lite 版打包配置 |
| `package.lite.json` | Lite 版 package 定义 |
| `requirements-runtime.lock.txt` | 运行时依赖锁定 |

## 不进 git 的内容

- `runtime/`（Python 运行时，约 1.9 GB）
- `models/`（嵌入模型）
- `node_modules/`
- 构建产物（`build/`、`build-lite/`、`artifacts/` 内的安装包）

这些在打包时现场生成或下载。

## 历史说明

本目录原为独立的本地仓库 `Memo_Installer`（8 个提交，**无远程备份**），
2026-11-20 合并进主仓库 `memo`，使打包器源码与应用代码同仓库、同 tag 管理，
避免出现"安装包版本与应用代码版本脱节"。

原本地目录 `Memo_Installer` 中的二进制资源（runtime / models / node_modules）如仍需用于打包，
可保留在原位置，或按需重新生成。
