"""Memo Agent 配置安装器。

面向非研发用户：自动生成/写入 MCP 配置，并复制 Memo Skill。
默认不会删除任何已有配置；写入前会备份原文件。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "install_output"


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def norm(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/")


def find_python() -> Path:
    venv_python = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    if venv_python.exists():
        return venv_python
    return Path(sys.executable)


def mcp_server_config() -> dict:
    python_path = find_python()
    db_path = PROJECT_ROOT / "data" / "memo.db"
    return {
        "command": norm(python_path),
        "args": [norm(PROJECT_ROOT / "scripts" / "run_mcp.py")],
        "env": {
            "MEMO_DB_PATH": norm(db_path),
            "MEMO_ENV": "production",
        },
    }


def full_mcp_config() -> dict:
    return {"mcpServers": {"memo": mcp_server_config()}}


def backup_file(path: Path) -> Path | None:
    if not path.exists():
        return None
    backup = path.with_suffix(path.suffix + f".bak-{stamp()}")
    shutil.copy2(path, backup)
    return backup


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        backup = backup_file(path)
        return {"_memo_note": f"原配置无法解析，已备份到 {backup}"}


def merge_mcp(path: Path, dry_run: bool = False) -> dict:
    data = load_json(path)
    data.setdefault("mcpServers", {})
    data["mcpServers"]["memo"] = mcp_server_config()
    if dry_run:
        return {"path": str(path), "dry_run": True, "config": data}
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = backup_file(path)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"path": str(path), "backup": str(backup) if backup else "无", "written": True}


def copy_skill(target_dir: Path, dry_run: bool = False) -> dict:
    src = PROJECT_ROOT / "SKILL.md"
    dst = target_dir / "memo" / "SKILL.md"
    if dry_run:
        return {"path": str(dst), "dry_run": True}
    dst.parent.mkdir(parents=True, exist_ok=True)
    backup = backup_file(dst)
    shutil.copy2(src, dst)
    return {"path": str(dst), "backup": str(backup) if backup else "无", "written": True}


def write_generated_files() -> list[dict]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    files: list[dict] = []
    mcp_file = OUTPUT_DIR / "memo_mcp_config.generated.json"
    mcp_file.write_text(json.dumps(full_mcp_config(), ensure_ascii=False, indent=2), encoding="utf-8")
    files.append({"path": str(mcp_file), "description": "通用 MCP 配置，可复制到任意 Agent"})

    prompt_file = OUTPUT_DIR / "memo_agent_prompt.generated.md"
    src = PROJECT_ROOT / "AGENT_PROMPT.md"
    if src.exists():
        prompt_file.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        files.append({"path": str(prompt_file), "description": "Agent 系统提示词，可复制到 Agent 的 System Prompt"})

    hana_file = OUTPUT_DIR / "hanaagent_mcp_ready_to_paste.json"
    hana_file.write_text(json.dumps({"memo": mcp_server_config()}, ensure_ascii=False, indent=2), encoding="utf-8")
    files.append({"path": str(hana_file), "description": "HanaAgent 设置页可粘贴的 memo 连接器配置"})

    qoder_file = OUTPUT_DIR / "qoder_mcp_ready_to_paste.json"
    qoder_file.write_text(json.dumps(full_mcp_config(), ensure_ascii=False, indent=2), encoding="utf-8")
    files.append({"path": str(qoder_file), "description": "Qoder / QoderWork 可粘贴的 MCP 配置"})
    return files


def install_hana(dry_run: bool = False) -> list[dict]:
    home = Path.home()
    results = [copy_skill(home / ".hanako" / "skills", dry_run=dry_run)]
    # HanaAgent 的 MCP 连接器通常从设置页管理。这里生成可粘贴配置，不强行改内部配置。
    return results


def install_workbuddy(dry_run: bool = False) -> list[dict]:
    home = Path.home()
    return [
        merge_mcp(home / ".workbuddy" / "mcp.json", dry_run=dry_run),
        copy_skill(home / ".workbuddy" / "skills", dry_run=dry_run),
    ]


def install_qoder(dry_run: bool = False) -> list[dict]:
    """兼容 Qoder / QoderWork。

    Qoder 系列的 MCP 配置入口在不同版本里可能不同，所以这里采用保守策略：
    1. 始终生成 install_output/qoder_mcp_ready_to_paste.json；
    2. 若常见本地目录已存在，则自动写入对应 mcp.json 并复制 Skill；
    3. 若目录不存在，不强行创建一堆未知目录，避免污染用户环境。
    """
    home = Path.home()
    candidates = [
        (home / ".qoder", "Qoder"),
        (home / ".qoderwork", "QoderWork"),
    ]
    results: list[dict] = []
    wrote = False
    for base, label in candidates:
        if base.exists():
            results.append({"detected": label, "path": str(base)})
            results.append(merge_mcp(base / "mcp.json", dry_run=dry_run))
            results.append(copy_skill(base / "skills", dry_run=dry_run))
            wrote = True
    if not wrote:
        results.append({
            "manual": True,
            "message": "未发现 ~/.qoder 或 ~/.qoderwork，已生成 install_output/qoder_mcp_ready_to_paste.json，请在 Qoder 设置页手动导入。",
        })
    return results


def install_claude(dry_run: bool = False) -> list[dict]:
    appdata = os.getenv("APPDATA")
    if not appdata:
        return [{"error": "未找到 APPDATA，无法定位 Claude Desktop 配置目录"}]
    return [merge_mcp(Path(appdata) / "Claude" / "claude_desktop_config.json", dry_run=dry_run)]


def install_cursor_project(dry_run: bool = False) -> list[dict]:
    return [merge_mcp(PROJECT_ROOT / ".cursor" / "mcp.json", dry_run=dry_run)]


def install_target(target: str, dry_run: bool = False) -> list[dict]:
    if target == "hana":
        return install_hana(dry_run)
    if target == "workbuddy":
        return install_workbuddy(dry_run)
    if target == "qoder":
        return install_qoder(dry_run)
    if target == "claude":
        return install_claude(dry_run)
    if target == "cursor":
        return install_cursor_project(dry_run)
    if target == "all":
        results: list[dict] = []
        for item in ["hana", "workbuddy", "qoder", "claude", "cursor"]:
            results.append({"target": item})
            results.extend(install_target(item, dry_run))
        return results
    raise ValueError(f"未知 target: {target}")


def choose_target() -> str:
    print("\n请选择要配置的 Agent：")
    print("  1. HanaAgent（推荐：复制 Skill，并生成 MCP 设置页可粘贴配置）")
    print("  2. WorkBuddy（自动写 ~/.workbuddy/mcp.json + Skill）")
    print("  3. Qoder / QoderWork（自动探测常见目录；否则生成可粘贴配置）")
    print("  4. Claude Desktop（自动写 Claude 配置）")
    print("  5. Cursor 当前项目（自动写 .cursor/mcp.json）")
    print("  6. 全部生成/安装")
    print("  0. 只生成配置文件，不写入任何 Agent")
    ans = input("请输入数字后回车：").strip()
    return {"1": "hana", "2": "workbuddy", "3": "qoder", "4": "claude", "5": "cursor", "6": "all", "0": "none"}.get(ans, "hana")


def main() -> int:
    parser = argparse.ArgumentParser(description="Memo Agent 配置安装器")
    parser.add_argument("--target", choices=["hana", "workbuddy", "qoder", "claude", "cursor", "all", "none"], default="")
    parser.add_argument("--dry-run", action="store_true", help="只预览，不写文件")
    parser.add_argument("--json", action="store_true", help="输出 JSON 结果")
    args = parser.parse_args()

    generated = write_generated_files()
    target = args.target or choose_target()
    results: list[dict] = [{"generated": generated}]
    if target != "none":
        results.append({"install_target": target})
        results.extend(install_target(target, dry_run=args.dry_run))

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print("\nMemo Agent 配置结果：")
        for item in results:
            print("- " + json.dumps(item, ensure_ascii=False))
        print("\n提示：HanaAgent 请打开 install_output/hanaagent_mcp_ready_to_paste.json 复制到设置页；Qoder 请打开 install_output/qoder_mcp_ready_to_paste.json 复制到设置页。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
