"""Memo 普通用户一键安装器（Windows 优先）。

设计目标：让非研发用户不用理解 pip、venv、MCP JSON，也能完成安装。
此脚本只做外围安装和配置，不修改 Memo 核心逻辑、不删除数据库。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VENV = PROJECT_ROOT / ".venv"
VENV_PY = VENV / "Scripts" / "python.exe"


def run(cmd: list[str], *, env: dict | None = None, dry_run: bool = False) -> int:
    printable = " ".join(f'"{x}"' if " " in x else x for x in cmd)
    print(f"\n> {printable}")
    if dry_run:
        return 0
    return subprocess.call(cmd, cwd=str(PROJECT_ROOT), env=env)


def find_base_python() -> str:
    candidates = []
    py = shutil.which("py")
    if py:
        candidates.append((py, [py, "-3"]))
    python = shutil.which("python")
    if python:
        candidates.append((python, [python]))
    if not candidates:
        raise RuntimeError("未找到 Python。请先安装 Python 3.11 或更高版本。")
    for _, cmd in candidates:
        try:
            out = subprocess.check_output(cmd + ["-c", "import sys; print(sys.version_info[:2])"], text=True)
            if "(3, 11)" in out or "(3, 12)" in out or "(3, 13)" in out or "(3, 14)" in out:
                return cmd[0] if len(cmd) == 1 else " ".join(cmd)
        except Exception:
            continue
    # 让后续 doctor 给出更明确错误
    return candidates[0][1][0]


def ensure_env(api_key: str = "", dry_run: bool = False) -> None:
    env_path = PROJECT_ROOT / ".env"
    example = PROJECT_ROOT / ".env.example"
    if env_path.exists():
        print("✓ .env 已存在，不覆盖")
        return
    print("准备创建 .env")
    text = example.read_text(encoding="utf-8") if example.exists() else "MEMO_DB_PATH=data/memo.db\n"
    if api_key:
        text = text.replace("LLM_API_KEY=sk-your-key-here", f"LLM_API_KEY={api_key}")
    if dry_run:
        print("dry-run：跳过写入 .env")
        return
    env_path.write_text(text, encoding="utf-8")
    print("✓ 已创建 .env。若还没填 API Key，请稍后打开 .env 填写。")


def ensure_venv(dry_run: bool = False) -> None:
    if VENV_PY.exists():
        print(f"✓ 已存在虚拟环境：{VENV_PY}")
        return
    base = find_base_python()
    if " " in base:
        cmd = base.split() + ["-m", "venv", str(VENV)]
    else:
        cmd = [base, "-m", "venv", str(VENV)]
    code = run(cmd, dry_run=dry_run)
    if code != 0:
        raise RuntimeError("创建 .venv 失败")


def install_dependencies(use_mirror: bool = False, dry_run: bool = False) -> None:
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    if use_mirror:
        env.setdefault("PIP_INDEX_URL", "https://pypi.tuna.tsinghua.edu.cn/simple")
        env.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    cmds = [
        [str(VENV_PY), "-m", "pip", "install", "--upgrade", "pip"],
        [str(VENV_PY), "-m", "pip", "install", "-r", "requirements.txt"],
    ]
    for cmd in cmds:
        code = run(cmd, env=env, dry_run=dry_run)
        if code != 0:
            raise RuntimeError("依赖安装失败。可尝试重新运行并选择国内镜像。")


def verify_torch(dry_run: bool = False) -> None:
    code = run([str(VENV_PY), "-c", "import torch; print('torch', torch.__version__)"], dry_run=dry_run)
    if code != 0:
        raise RuntimeError(
            "PyTorch 导入失败。请先重新运行 install.bat；如果仍失败，安装 Microsoft Visual C++ Redistributable 2015-2022 x64 后重启电脑。"
        )


def init_database(dry_run: bool = False) -> None:
    code = run([str(VENV_PY), "-c", "from memo.core.engine import engine; engine.init(); print('Memo database OK')"], dry_run=dry_run)
    if code != 0:
        raise RuntimeError("数据库初始化失败")


def run_smoke(dry_run: bool = False) -> None:
    code = run([str(VENV_PY), "scripts/smoke_test_mcp.py"], dry_run=dry_run)
    if code != 0:
        raise RuntimeError("安装后自检失败")


def configure_agent(target: str, dry_run: bool = False) -> None:
    python = VENV_PY if VENV_PY.exists() else Path(sys.executable)
    cmd = [str(python), "scripts/install_agent.py", "--target", target]
    if dry_run:
        cmd.append("--dry-run")
    code = run(cmd, dry_run=False)
    if code != 0:
        raise RuntimeError("Agent 配置失败")


def ask_yes_no(text: str, default: bool = True) -> bool:
    suffix = "Y/n" if default else "y/N"
    ans = input(f"{text} ({suffix})：").strip().lower()
    if not ans:
        return default
    return ans in {"y", "yes", "是", "好", "1"}


def ask_agent() -> str:
    print("\n你主要使用哪个 Agent？")
    print("  1. HanaAgent")
    print("  2. WorkBuddy")
    print("  3. Claude Desktop")
    print("  4. Cursor")
    print("  5. 全部配置")
    print("  0. 暂不配置，只生成配置文件")
    ans = input("请输入数字后回车，默认 1：").strip() or "1"
    return {"1": "hana", "2": "workbuddy", "3": "claude", "4": "cursor", "5": "all", "0": "none"}.get(ans, "hana")


def main() -> int:
    parser = argparse.ArgumentParser(description="Memo 普通用户一键安装器")
    parser.add_argument("--target", choices=["hana", "workbuddy", "claude", "cursor", "all", "none"], default="")
    parser.add_argument("--api-key", default="", help="可选：直接写入 .env 的 LLM_API_KEY")
    parser.add_argument("--use-mirror", action="store_true", help="使用国内 pip/HuggingFace 镜像")
    parser.add_argument("--skip-deps", action="store_true", help="跳过依赖安装，适合已打包 .venv 的发布包")
    parser.add_argument("--dry-run", action="store_true", help="只预演，不创建环境、不安装依赖")
    args = parser.parse_args()

    print("=" * 64)
    print("Memo 一键安装器")
    print("=" * 64)
    print(f"项目目录：{PROJECT_ROOT}")
    print("此安装器不会删除你的数据库，也不会修改 Memo 核心代码。")

    use_mirror = args.use_mirror
    if not use_mirror and not args.dry_run:
        use_mirror = ask_yes_no("如果你在国内网络环境，建议使用镜像加速。是否使用镜像", True)

    target = args.target or ("none" if args.dry_run else ask_agent())

    try:
        ensure_env(args.api_key, dry_run=args.dry_run)
        ensure_venv(dry_run=args.dry_run)
        # 先生成/写入 Agent 配置。即使后续依赖或数据库初始化失败，用户也能拿到 install_output 里的 MCP 配置。
        configure_agent(target, dry_run=args.dry_run)
        if not args.skip_deps:
            install_dependencies(use_mirror=use_mirror, dry_run=args.dry_run)
            verify_torch(dry_run=args.dry_run)
        else:
            print("✓ 已跳过依赖安装")
        init_database(dry_run=args.dry_run)
        run_smoke(dry_run=args.dry_run)
    except Exception as exc:
        print("\n安装没有完成：")
        print(f"  {exc}")
        print("请把这段窗口内容截图发给维护者。")
        return 1

    print("\n" + "=" * 64)
    print("安装完成")
    print("=" * 64)
    print("下一步：")
    print("  1. 如果 .env 里还没填 API Key，请先填写 LLM_API_KEY")
    print("  2. 双击 start_all.bat 启动 Memo")
    print("  3. 浏览器打开 http://localhost:9120 查看看板")
    print("  4. 重启你的 Agent，让 MCP 配置生效")
    print("  5. HanaAgent 用户如未自动导入 MCP，请复制 install_output/hanaagent_mcp_ready_to_paste.json 到设置页")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
