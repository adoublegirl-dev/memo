"""Memo 安装后冒烟测试。

只做轻量连通检查：依赖、配置、数据库、MCP server 可导入、统计接口可读。
不会写入用户记忆，不会调用 LLM。
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def check(name: str, ok: bool, detail: str = "") -> dict:
    return {"name": name, "ok": bool(ok), "detail": detail}


def main() -> int:
    parser = argparse.ArgumentParser(description="Memo MCP 安装后冒烟测试")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    results: list[dict] = []
    results.append(check("项目目录", PROJECT_ROOT.exists(), str(PROJECT_ROOT)))
    results.append(check("run_mcp.py", (PROJECT_ROOT / "scripts" / "run_mcp.py").exists()))
    results.append(check(".env", (PROJECT_ROOT / ".env").exists(), "不存在时会使用默认配置，但建议填写 API Key"))

    for mod in ["openai", "numpy", "jieba", "sentence_transformers", "dotenv", "mcp"]:
        try:
            __import__(mod)
            results.append(check(f"依赖 {mod}", True))
        except Exception as exc:
            results.append(check(f"依赖 {mod}", False, str(exc)))

    try:
        from memo.core.config import config

        db = Path(config.db_path)
        results.append(check("数据库路径", True, str(db)))
        db.parent.mkdir(parents=True, exist_ok=True)
        results.append(check("数据库目录可用", db.parent.exists(), str(db.parent)))
    except Exception as exc:
        results.append(check("读取 Memo 配置", False, str(exc)))
        db = None

    try:
        from memo.mcp.server import main as _mcp_main  # noqa: F401

        results.append(check("MCP Server 可导入", True))
    except Exception as exc:
        results.append(check("MCP Server 可导入", False, str(exc)))

    try:
        from memo.core.engine import engine

        engine.init()
        stats = engine.stats()
        results.append(check("Memo Engine 初始化", True))
        results.append(check("统计接口", True, json.dumps(stats, ensure_ascii=False)))
    except Exception as exc:
        results.append(check("Memo Engine 初始化/统计", False, str(exc)))

    if db and db.exists():
        try:
            conn = sqlite3.connect(str(db))
            version = conn.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()
            conn.close()
            results.append(check("schema_version", True, str(version[0] if version else 0)))
        except Exception as exc:
            results.append(check("schema_version", False, str(exc)))

    ok = all(item["ok"] for item in results if not (item["name"] == ".env"))
    if args.json:
        print(json.dumps({"ok": ok, "results": results}, ensure_ascii=False, indent=2))
    else:
        print("=" * 60)
        print("Memo 安装后自检")
        print("=" * 60)
        for item in results:
            icon = "✓" if item["ok"] else "✗"
            detail = f"：{item['detail']}" if item.get("detail") else ""
            print(f"{icon} {item['name']}{detail}")
        print("=" * 60)
        print("结果：" + ("通过" if ok else "存在问题，请把上面的 ✗ 截图发给维护者"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
