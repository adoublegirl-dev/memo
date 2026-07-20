"""安全构建 Memo 发布包。

默认排除 .env、真实数据库、日志、node_modules、测试/开发库等敏感或大体积内容。
"""

from __future__ import annotations

import argparse
import fnmatch
import zipfile
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

EXCLUDES = [
    ".git/*",
    ".env",
    "data/*.db",
    "data/*.db-*",
    "data/backups/*",
    "data/pids/*",
    "logs/*",
    "node_modules/*",
    "dashboard/node_modules/*",
    ".venv/*",
    "install_output/*",
    "docs/prototypes/*",
    "__pycache__/*",
    "*.pyc",
    "*.log",
    ".pytest_cache/*",
    "scripts/_*.json",
    "scripts/_check_*.py",
    "dist/*",
    "memo/data/*",
    "_zip_compare/*",
]

INCLUDES_REQUIRED = [
    "README.md",
    ".env.example",
    "requirements.txt",
    "pyproject.toml",
    "scripts/run_mcp.py",
    "scripts/memo_dashboard.py",
]


def rel(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


def excluded(relative: str) -> bool:
    return any(fnmatch.fnmatch(relative, pattern) for pattern in EXCLUDES)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="", help="输出 zip 路径，默认 dist/Memo-release-时间戳.zip")
    parser.add_argument("--include-dist", action="store_true", help="包含 dashboard/dist 构建产物")
    parser.add_argument("--include-venv", action="store_true", help="包含 .venv 便携运行环境（仅适合同系统分发，包会很大）")
    args = parser.parse_args()

    for item in INCLUDES_REQUIRED:
        if not (PROJECT_ROOT / item).exists():
            print(f"缺少必要文件: {item}")
            return 1

    if args.output:
        output = Path(args.output)
        if not output.is_absolute():
            output = PROJECT_ROOT / output
    else:
        output = PROJECT_ROOT / "dist" / f"Memo-release-{datetime.now():%Y%m%d-%H%M%S}.zip"
    output.parent.mkdir(parents=True, exist_ok=True)

    count = 0
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in PROJECT_ROOT.rglob("*"):
            if not path.is_file():
                continue
            relative = rel(path)
            if relative == rel(output):
                continue
            if relative.startswith(".venv/") and args.include_venv:
                pass
            elif excluded(relative):
                continue
            if relative.startswith("dashboard/dist/") and not args.include_dist:
                continue
            zf.write(path, relative)
            count += 1

    print(f"发布包已生成: {output}")
    print(f"包含文件数: {count}")
    print("已排除: .env、data/*.db、data/backups、data/pids、logs、node_modules、测试/开发库")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
