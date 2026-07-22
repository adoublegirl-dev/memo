"""Memo 全量安装/升级前检测器。

只读：不创建文件、不安装依赖、不执行 migration。
输出给 full_install.py 使用，也方便用户把报告发给维护者。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VENV_PY = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"


def run_capture(cmd: list[str], timeout: int = 10) -> tuple[bool, str]:
    try:
        out = subprocess.check_output(cmd, cwd=str(PROJECT_ROOT), stderr=subprocess.STDOUT, text=True, timeout=timeout)
        return True, out.strip()
    except Exception as exc:
        return False, str(exc)


def command_version(command: str, args: list[str]) -> dict[str, Any]:
    path = shutil.which(command)
    if not path:
        return {"ok": False, "path": "", "version": "未找到"}
    ok, out = run_capture([path] + args)
    return {"ok": ok, "path": path, "version": out.splitlines()[0] if out else "未知"}


def sqlite_schema_version(db_path: Path) -> dict[str, Any]:
    if not db_path.exists():
        return {"exists": False, "schema_version": None, "detail": "数据库不存在"}
    try:
        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()
        conn.close()
        return {"exists": True, "schema_version": int(row[0]) if row else 0, "detail": "ok"}
    except Exception as exc:
        return {"exists": True, "schema_version": None, "detail": f"读取失败: {exc}"}


def latest_migration_version() -> int:
    versions: list[int] = []
    for path in (PROJECT_ROOT / "memo" / "store" / "migrations").glob("*.sql"):
        try:
            versions.append(int(path.stem.split("_", 1)[0]))
        except Exception:
            continue
    return max(versions) if versions else 0


def check_python_deps() -> dict[str, Any]:
    py = VENV_PY if VENV_PY.exists() else Path(sys.executable)
    modules = ["openai", "numpy", "jieba", "sentence_transformers", "dotenv", "mcp"]
    code = "import importlib.util, json; mods=%r; print(json.dumps({m: (importlib.util.find_spec(m) is not None) for m in mods}))" % modules
    ok, out = run_capture([str(py), "-c", code], timeout=20)
    if not ok:
        return {"ok": False, "python": str(py), "modules": {}, "detail": out}
    try:
        modules_status = json.loads(out)
    except Exception:
        modules_status = {}
    return {"ok": bool(modules_status) and all(modules_status.values()), "python": str(py), "modules": modules_status}


def check_desktop_deps() -> dict[str, Any]:
    electron = PROJECT_ROOT / "node_modules" / "electron"
    builder = PROJECT_ROOT / "node_modules" / "electron-builder"
    return {
        "ok": electron.exists() and builder.exists(),
        "electron": electron.exists(),
        "electron_builder": builder.exists(),
        "package_lock": (PROJECT_ROOT / "package-lock.json").exists(),
    }


def check_mcp_generated() -> dict[str, Any]:
    output = PROJECT_ROOT / "install_output"
    generated = {
        "hana": output / "hanaagent_mcp_ready_to_paste.json",
        "qoder": output / "qoder_mcp_ready_to_paste.json",
        "generic": output / "memo_mcp_config.generated.json",
    }
    return {"ok": all(p.exists() for p in generated.values()), "files": {k: str(v) for k, v in generated.items()}, "exists": {k: v.exists() for k, v in generated.items()}}


def guess_mode(env_exists: bool, db_exists: bool, deps_ok: bool, desktop_ok: bool) -> str:
    if env_exists or db_exists:
        if deps_ok and desktop_ok:
            return "upgrade"
        return "repair"
    return "install"


def build_report() -> dict[str, Any]:
    env_path = PROJECT_ROOT / ".env"
    db_path = PROJECT_ROOT / "data" / "memo.db"
    database = sqlite_schema_version(db_path)
    latest = latest_migration_version()
    py_deps = check_python_deps()
    desktop_deps = check_desktop_deps()
    env_exists = env_path.exists()

    recommendations: list[str] = []
    if not env_exists:
        recommendations.append("创建 .env 或从 .env.example 复制后填写 API Key")
    if not VENV_PY.exists():
        recommendations.append("创建 .venv 虚拟环境")
    if not py_deps["ok"]:
        recommendations.append("安装/修复 Python 依赖")
    if not desktop_deps["ok"]:
        recommendations.append("安装/修复桌面助手 npm 依赖")
    if database["exists"] and database.get("schema_version") is not None and database["schema_version"] < latest:
        recommendations.append(f"数据库需要从 schema {database['schema_version']} 升级到 {latest}，升级前必须备份")
    if not database["exists"]:
        recommendations.append("初始化数据库")

    mode = guess_mode(env_exists, bool(database["exists"]), bool(py_deps["ok"]), bool(desktop_deps["ok"]))

    return {
        "project_root": str(PROJECT_ROOT),
        "mode_guess": mode,
        "python": command_version("python", ["--version"]),
        "node": command_version("node", ["--version"]),
        "npm": command_version("npm", ["--version"]),
        "env": {"exists": env_exists, "path": str(env_path)},
        "venv": {"exists": VENV_PY.exists(), "python": str(VENV_PY)},
        "database": {**database, "path": str(db_path), "latest_migration": latest},
        "python_dependencies": py_deps,
        "desktop_dependencies": desktop_deps,
        "mcp_generated": check_mcp_generated(),
        "recommendations": recommendations,
    }


def print_human(report: dict[str, Any]) -> None:
    print("=" * 64)
    print("Memo 安装/升级检测")
    print("=" * 64)
    print(f"项目目录：{report['project_root']}")
    print(f"建议模式：{report['mode_guess']}")
    print(f"Python：{'✓' if report['python']['ok'] else '✗'} {report['python']['version']}")
    print(f"Node：{'✓' if report['node']['ok'] else '✗'} {report['node']['version']}")
    print(f"npm：{'✓' if report['npm']['ok'] else '✗'} {report['npm']['version']}")
    print(f".env：{'✓' if report['env']['exists'] else '✗'}")
    print(f".venv：{'✓' if report['venv']['exists'] else '✗'}")
    db = report["database"]
    print(f"数据库：{'✓' if db['exists'] else '✗'} schema={db.get('schema_version')} latest={db.get('latest_migration')}")
    print(f"Python 依赖：{'✓' if report['python_dependencies']['ok'] else '✗'}")
    print(f"桌面助手依赖：{'✓' if report['desktop_dependencies']['ok'] else '✗'}")
    if report["recommendations"]:
        print("\n建议操作：")
        for item in report["recommendations"]:
            print(f"- {item}")
    else:
        print("\n建议操作：无，环境看起来正常。")


def main() -> int:
    parser = argparse.ArgumentParser(description="Memo 安装/升级检测器")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()
    report = build_report()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_human(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
