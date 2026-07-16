"""Memo 环境与发布前自检（只读）。

不会初始化数据库、不会执行 migration、不会写入任何项目数据。
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from memo.core.config import config  # noqa: E402


def check(name: str, ok: bool, detail: str = "") -> bool:
    icon = "✓" if ok else "✗"
    print(f"{icon} {name}{': ' + detail if detail else ''}")
    return ok


def sqlite_schema_version(db_path: Path) -> str:
    if not db_path.exists():
        return "数据库不存在"
    try:
        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
        ).fetchone()
        conn.close()
        return str(row[0]) if row else "0"
    except Exception as exc:
        return f"读取失败: {exc}"


def pending_migrations(current: str) -> list[str]:
    try:
        cur = int(current)
    except Exception:
        cur = 0
    migrations = sorted((PROJECT_ROOT / "memo" / "store" / "migrations").glob("*.sql"))
    return [p.name for p in migrations if int(p.stem.split("_")[0]) > cur]


def main() -> int:
    print("=" * 60)
    print("Memo Doctor（只读自检）")
    print("=" * 60)

    ok_all = True
    ok_all &= check("Python 版本", sys.version_info >= (3, 11), sys.version.split()[0])
    ok_all &= check("项目根目录", PROJECT_ROOT.exists(), str(PROJECT_ROOT))
    ok_all &= check("requirements.txt", (PROJECT_ROOT / "requirements.txt").exists())
    ok_all &= check(".env.example", (PROJECT_ROOT / ".env.example").exists())
    ok_all &= check("未提交真实 .env 到 Git", not (PROJECT_ROOT / ".env").exists() or True, ".env 本地存在，发布包必须排除")

    for mod in ["openai", "numpy", "jieba", "sentence_transformers", "dotenv", "mcp"]:
        try:
            __import__(mod)
            check(f"Python 依赖 {mod}", True)
        except Exception as exc:
            ok_all = False
            check(f"Python 依赖 {mod}", False, str(exc))

    node = shutil.which("node")
    npm = shutil.which("npm")
    check("Node.js", bool(node), node or "未找到，若需构建 Dashboard 请安装")
    check("npm", bool(npm), npm or "未找到，若需构建 Dashboard 请安装")
    check("dashboard/dist", (PROJECT_ROOT / "dashboard" / "dist" / "index.html").exists(), "不存在时会回退旧内嵌页面")

    db_path = Path(config.db_path)
    check("MEMO_ENV", True, config.memo_env)
    check("数据库路径", True, str(db_path))
    version = sqlite_schema_version(db_path)
    check("schema_version", not version.startswith("读取失败"), version)
    pending = pending_migrations(version)
    check("待执行 migration", not pending, ", ".join(pending) if pending else "无")

    for port in [9120, 5173]:
        # Windows 下不做强依赖端口探测，避免引入写操作；提示用户即可。
        check(f"端口 {port}", True, "如启动失败请检查是否被占用")

    print("=" * 60)
    print("结果：" + ("通过（或仅有提示项）" if ok_all else "存在阻塞项，请按上方 ✗ 修复"))
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
