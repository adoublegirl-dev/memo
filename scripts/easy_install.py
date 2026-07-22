"""Memo 普通用户一键安装器（Windows 优先）。

设计目标：让非研发用户不用理解 pip、venv、MCP JSON，也能完成安装。
此脚本只做外围安装和配置，不修改 Memo 核心逻辑、不删除数据库。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VENV = PROJECT_ROOT / ".venv"
VENV_PY = VENV / "Scripts" / "python.exe"
PLACEHOLDER_KEYS = {"", "sk-your-key-here", "your-api-key", "填写你的key", "请填写"}

LLM_PRESETS = {
    "1": {
        "label": "DeepSeek V4 Flash（默认推荐，便宜，适合持续记忆写入）",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-flash",
    },
    "2": {
        "label": "DeepSeek V4 Pro（更强，成本更高）",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-pro",
    },
    "3": {
        "label": "OpenAI GPT-4o mini",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
    },
    "4": {
        "label": "OpenAI GPT-4.1 mini",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4.1-mini",
    },
}


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


def parse_env_text(text: str) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        k, v = stripped.split("=", 1)
        data[k.strip()] = v.strip()
    return data


def has_valid_key(env_values: dict[str, str]) -> bool:
    key = (env_values.get("LLM_API_KEY") or "").strip()
    return bool(key) and key.lower() not in PLACEHOLDER_KEYS and not key.startswith("sk-your")


def upsert_env_text(text: str, updates: dict[str, str]) -> str:
    lines = text.splitlines()
    seen = set()
    out = []
    for line in lines:
        if "=" in line and not line.strip().startswith("#"):
            k = line.split("=", 1)[0].strip()
            if k in updates:
                out.append(f"{k}={updates[k]}")
                seen.add(k)
                continue
        out.append(line)
    if updates:
        if out and out[-1].strip():
            out.append("")
        for k, v in updates.items():
            if k not in seen:
                out.append(f"{k}={v}")
    return "\n".join(out).rstrip() + "\n"


def choose_llm_config() -> dict[str, str] | None:
    print("\n可选：配置 LLM API Key")
    print("Memo 没有 Key 也能安装，但记忆提取/总结会降级。你也可以先跳过，之后编辑 .env。")
    print("提示：记忆写入、总结和治理会持续消耗 token，建议优先使用便宜模型，默认推荐 deepseek-v4-flash。")
    print("\n请选择模型供应商：")
    for key, preset in LLM_PRESETS.items():
        print(f"  {key}. {preset['label']}")
    print("  5. 自定义 OpenAI-compatible 接口")
    print("  0. 跳过，稍后自己在 .env 配置")
    ans = input("请输入数字后回车，默认 1：").strip() or "1"
    if ans == "0":
        return None
    if ans == "5":
        base_url = input("请输入 Base URL，例如 https://api.example.com/v1：").strip()
        model = input("请输入模型名，例如 qwen-plus / gpt-4o-mini：").strip()
        if not base_url or not model:
            print("Base URL 或模型名为空，已跳过 Key 配置。")
            return None
    else:
        preset = LLM_PRESETS.get(ans, LLM_PRESETS["1"])
        base_url = preset["base_url"]
        model = preset["model"]
        print(f"已选择：{preset['label']}")
    api_key = input("请输入 API Key（输入为空则跳过）：").strip()
    if not api_key:
        return None
    return {"LLM_API_KEY": api_key, "LLM_BASE_URL": base_url, "MEMO_EXTRACTION_MODEL": model, "MEMO_GATING_MODEL": model}


def test_llm_connection(base_url: str, api_key: str, model: str, timeout: int = 20) -> tuple[bool, str]:
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 3,
        "temperature": 0,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(2048).decode("utf-8", errors="ignore")
            if 200 <= resp.status < 300:
                return True, "连接测试通过"
            return False, f"HTTP {resp.status}: {body[:300]}"
    except urllib.error.HTTPError as e:
        body = e.read(1024).decode("utf-8", errors="ignore")
        return False, f"HTTP {e.code}: {body[:300]}"
    except Exception as e:
        return False, str(e)


def ensure_env(api_key: str = "", dry_run: bool = False, skip_key_config: bool = False) -> None:
    env_path = PROJECT_ROOT / ".env"
    example = PROJECT_ROOT / ".env.example"
    if env_path.exists():
        text = env_path.read_text(encoding="utf-8")
        values = parse_env_text(text)
        if has_valid_key(values):
            print("✓ .env 已存在且检测到 API Key，跳过 Key 配置")
            return
        print("✓ .env 已存在，但未检测到有效 API Key")
    else:
        print("准备创建 .env")
        text = example.read_text(encoding="utf-8") if example.exists() else "MEMO_DB_PATH=data/memo.db\n"
        values = parse_env_text(text)

    updates: dict[str, str] = {}
    if api_key:
        updates["LLM_API_KEY"] = api_key
    elif not skip_key_config and not dry_run:
        chosen = choose_llm_config()
        if chosen:
            while True:
                ok, msg = test_llm_connection(chosen["LLM_BASE_URL"], chosen["LLM_API_KEY"], chosen["MEMO_EXTRACTION_MODEL"])
                if ok:
                    print(f"✓ {msg}")
                    updates.update(chosen)
                    break
                print("\n连接测试失败：")
                print(f"  {msg}")
                print("你可以：1 重试输入  2 跳过，稍后在 .env 配置")
                retry = input("请输入 1 或 2，默认 1：").strip() or "1"
                if retry == "2":
                    break
                chosen = choose_llm_config()
                if not chosen:
                    break
    else:
        print("已跳过 API Key 配置。之后可编辑 .env 填写 LLM_API_KEY。")

    if updates:
        text = upsert_env_text(text, updates)
    elif "LLM_API_KEY" not in values:
        text = upsert_env_text(text, {"LLM_API_KEY": "sk-your-key-here"})

    if dry_run:
        print("dry-run：跳过写入 .env")
        return
    env_path.write_text(text, encoding="utf-8")
    if updates:
        print("✓ 已写入 .env 并保存模型配置")
    else:
        print("✓ 已创建/保留 .env。后续可打开 .env 填写 LLM_API_KEY。")


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
    print("  3. Qoder / QoderWork")
    print("  4. Claude Desktop")
    print("  5. Cursor")
    print("  6. 全部配置")
    print("  0. 暂不配置，只生成配置文件")
    ans = input("请输入数字后回车，默认 1：").strip() or "1"
    return {"1": "hana", "2": "workbuddy", "3": "qoder", "4": "claude", "5": "cursor", "6": "all", "0": "none"}.get(ans, "hana")


def print_completion(target: str) -> None:
    print("\n" + "=" * 64)
    print("安装完成")
    print("=" * 64)
    print("Memo 本体已经安装成功。")
    print("\n下一步：")
    print("  1. 双击 start_all.bat 启动 Memo，或打开桌面伴侣启动服务")
    print("  2. 浏览器打开 http://localhost:9120 查看看板")
    print("  3. 在你使用的 Agent 中配置并启用 MCP")
    print("\n配置文件位置：")
    print("  - 通用 MCP 配置：install_output/memo_mcp_config.generated.json")
    print("  - HanaAgent 粘贴用：install_output/hanaagent_mcp_ready_to_paste.json")
    print("  - Qoder 粘贴用：install_output/qoder_mcp_ready_to_paste.json")
    print("  - Agent 提示词：install_output/memo_agent_prompt.generated.md")
    if target in {"workbuddy", "claude", "cursor", "qoder", "all"}:
        print("\n部分 Agent 已尝试自动写入配置；如果 Agent 里没看到 Memo MCP，请复制上面的 ready-to-paste 配置手动启用。")
    else:
        print("\nHanaAgent 通常需要到设置页手动粘贴 MCP JSON，并启用 Memo MCP。")
    print("\n如果刚才跳过了 API Key：")
    print(f"  请稍后编辑 {PROJECT_ROOT / '.env'}，填写 LLM_API_KEY / LLM_BASE_URL / 模型名。")


def main() -> int:
    parser = argparse.ArgumentParser(description="Memo 普通用户一键安装器")
    parser.add_argument("--target", choices=["hana", "workbuddy", "qoder", "claude", "cursor", "all", "none"], default="")
    parser.add_argument("--api-key", default="", help="可选：直接写入 .env 的 LLM_API_KEY")
    parser.add_argument("--skip-key-config", action="store_true", help="跳过交互式 API Key 配置")
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
        ensure_env(args.api_key, dry_run=args.dry_run, skip_key_config=args.skip_key_config)
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

    print_completion(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
