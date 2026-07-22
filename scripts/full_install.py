"""Memo 全量安装器 / 升级器。

幂等执行：老用户升级、新用户安装、依赖修复、MCP 更新、桌面助手准备共用一个入口。
默认保护 .env、data/、logs/，不会删除用户数据。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VENV = PROJECT_ROOT / ".venv"
VENV_PY = VENV / "Scripts" / "python.exe"
BACKUP_DIR = PROJECT_ROOT / "data" / "backups"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.install_doctor import build_report  # noqa: E402
from scripts.easy_install import ensure_env as ensure_llm_env  # noqa: E402


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def run(cmd: list[str], *, dry_run: bool = False, env: dict[str, str] | None = None, check: bool = True) -> int:
    printable = " ".join(f'"{x}"' if " " in x else x for x in cmd)
    print(f"\n> {printable}")
    if dry_run:
        return 0
    code = subprocess.call(cmd, cwd=str(PROJECT_ROOT), env=env)
    if check and code != 0:
        raise RuntimeError(f"命令失败：{printable}")
    return code


def find_base_python() -> list[str]:
    py = shutil.which("py")
    if py:
        return [py, "-3"]
    python = shutil.which("python")
    if python:
        return [python]
    raise RuntimeError("未找到 Python。请先安装 Python 3.11 或更高版本。")


def ensure_env(api_key: str = "", dry_run: bool = False, skip_key_config: bool = False) -> None:
    ensure_llm_env(api_key=api_key, dry_run=dry_run, skip_key_config=skip_key_config)


def ensure_venv(dry_run: bool = False) -> None:
    if VENV_PY.exists():
        print(f"✓ .venv 已存在：{VENV_PY}")
        return
    cmd = find_base_python() + ["-m", "venv", str(VENV)]
    run(cmd, dry_run=dry_run)


def install_python_deps(use_mirror: bool = False, dry_run: bool = False) -> None:
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    if use_mirror:
        env.setdefault("PIP_INDEX_URL", "https://pypi.tuna.tsinghua.edu.cn/simple")
        env.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    run([str(VENV_PY), "-m", "pip", "install", "--upgrade", "pip"], dry_run=dry_run, env=env)
    run([str(VENV_PY), "-m", "pip", "install", "-r", "requirements.txt"], dry_run=dry_run, env=env)


def backup_database(dry_run: bool = False) -> Path | None:
    db = PROJECT_ROOT / "data" / "memo.db"
    if not db.exists():
        print("数据库不存在，无需备份")
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup = BACKUP_DIR / f"memo-before-full-install-{stamp()}.db"
    print(f"准备备份数据库：{backup}")
    if not dry_run:
        shutil.copy2(db, backup)
    return backup


def init_or_migrate_database(dry_run: bool = False) -> None:
    # engine.init 会执行必要 migration；调用前由 full installer 做数据库备份。
    run([str(VENV_PY), "-c", "from memo.core.engine import engine; engine.init(); print('Memo database OK')"], dry_run=dry_run)


def configure_agent(target: str, dry_run: bool = False) -> None:
    python = VENV_PY if VENV_PY.exists() else Path(sys.executable)
    if target == "none":
        print("✓ 跳过 Agent MCP 写入，只保留生成配置")
        run([str(python), "scripts/install_agent.py", "--target", "none"] + (["--dry-run"] if dry_run else []), dry_run=False)
        return
    cmd = [str(python), "scripts/install_agent.py", "--target", target]
    if dry_run:
        cmd.append("--dry-run")
    run(cmd, dry_run=False)


def install_desktop_deps(dry_run: bool = False) -> None:
    npm = shutil.which("npm")
    if not npm:
        raise RuntimeError("未找到 npm。请先安装 Node.js，或跳过桌面助手安装。")
    run([npm, "install"], dry_run=dry_run)


def pack_desktop(dry_run: bool = False) -> None:
    npm = shutil.which("npm")
    if not npm:
        raise RuntimeError("未找到 npm，无法打包桌面助手。")
    env = os.environ.copy()
    env.setdefault("CSC_IDENTITY_AUTO_DISCOVERY", "false")
    run([npm, "run", "desktop:pack"], dry_run=dry_run, env=env)


def run_smoke(dry_run: bool = False) -> None:
    run([str(VENV_PY), "scripts/smoke_test_mcp.py"], dry_run=dry_run)


def ask_yes_no(text: str, default: bool = True) -> bool:
    suffix = "Y/n" if default else "y/N"
    ans = input(f"{text} ({suffix})：").strip().lower()
    if not ans:
        return default
    return ans in {"y", "yes", "是", "好", "1"}


def choose_target(default: str = "hana") -> str:
    print("\n请选择要配置/更新 MCP 的 Agent：")
    print("  1. HanaAgent")
    print("  2. WorkBuddy")
    print("  3. Qoder / QoderWork")
    print("  4. Claude Desktop")
    print("  5. Cursor")
    print("  6. 全部")
    print("  0. 暂不配置")
    ans = input("请输入数字后回车，默认 1：").strip() or "1"
    return {"1": "hana", "2": "workbuddy", "3": "qoder", "4": "claude", "5": "cursor", "6": "all", "0": "none"}.get(ans, default)


def resolve_mode(mode: str) -> str:
    if mode != "auto":
        return mode
    report = build_report()
    return str(report["mode_guess"])


def main() -> int:
    parser = argparse.ArgumentParser(description="Memo 全量安装器 / 升级器")
    parser.add_argument("--mode", choices=["auto", "install", "upgrade", "repair", "doctor"], default="auto")
    parser.add_argument("--target", choices=["hana", "workbuddy", "qoder", "claude", "cursor", "all", "none"], default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--skip-key-config", action="store_true", help="跳过交互式 API Key 配置")
    parser.add_argument("--use-mirror", action="store_true")
    parser.add_argument("--skip-python-deps", action="store_true")
    parser.add_argument("--skip-desktop", action="store_true")
    parser.add_argument("--pack-desktop", action="store_true", help="安装后生成 win-unpacked 桌面应用")
    parser.add_argument("--skip-mcp", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print("=" * 64)
    print("Memo 全量安装器 / 升级器")
    print("=" * 64)
    print(f"项目目录：{PROJECT_ROOT}")
    print("安全声明：不会覆盖 .env，不会删除 data/、logs/，MCP 只合并 memo 项。")

    if args.mode == "doctor":
        report = build_report()
        print(__import__("json").dumps(report, ensure_ascii=False, indent=2))
        return 0

    mode = resolve_mode(args.mode)
    print(f"执行模式：{mode}")

    use_mirror = args.use_mirror
    if not use_mirror and not args.dry_run:
        use_mirror = ask_yes_no("是否使用国内镜像安装 Python 依赖", True)

    target = "none" if args.skip_mcp else (args.target or ("none" if args.dry_run else choose_target()))

    try:
        ensure_env(args.api_key, dry_run=args.dry_run, skip_key_config=args.skip_key_config)
        ensure_venv(dry_run=args.dry_run)

        if mode in {"upgrade", "repair"}:
            backup_database(dry_run=args.dry_run)

        if not args.skip_python_deps:
            install_python_deps(use_mirror=use_mirror, dry_run=args.dry_run)
        else:
            print("✓ 跳过 Python 依赖安装")

        init_or_migrate_database(dry_run=args.dry_run)

        if not args.skip_mcp:
            configure_agent(target, dry_run=args.dry_run)
        else:
            print("✓ 跳过 MCP 配置")

        if not args.skip_desktop:
            install_desktop_deps(dry_run=args.dry_run)
            if args.pack_desktop:
                pack_desktop(dry_run=args.dry_run)
        else:
            print("✓ 跳过桌面助手依赖")

        run_smoke(dry_run=args.dry_run)
    except Exception as exc:
        print("\n安装/升级未完成：")
        print(f"  {exc}")
        print("可运行 python scripts/install_doctor.py 查看环境报告。")
        return 1

    print("\n" + "=" * 64)
    print("Memo 安装/升级预演完成" if args.dry_run else "Memo 安装/升级完成")
    print("=" * 64)
    print("下一步：")
    print("  1. 启动 Memo 服务：start_all.bat，或用桌面助手启动服务")
    print("  2. 打开看板：http://localhost:9120")
    print("  3. 到对应 Agent 中配置并启用 MCP，然后重启 Agent")
    print("  4. 配置文件在 install_output/，HanaAgent/Qoder 用户可复制 ready-to-paste JSON")
    print("  5. 如果刚才跳过 API Key，可稍后编辑 .env 填写 LLM_API_KEY / LLM_BASE_URL / 模型名")
    print("  6. 若需要桌面软件 exe：npm run desktop:pack 或 npm run desktop:dist")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
