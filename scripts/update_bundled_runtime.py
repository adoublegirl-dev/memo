"""Safely update a packaged Memo runtime from a GitHub source archive.

This updater is for Electron/NSIS installs whose resources/app directory is not
a Git repository. It overlays service code only and never touches local data,
.env, databases, WAL/SHM files, logs, backups, or the running desktop shell.

Real execution requires:
    python scripts/update_bundled_runtime.py --apply --confirm UPDATE_BUNDLED
"""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

DEFAULT_ARCHIVE_URL = "https://github.com/adoublegirl-dev/memo/archive/refs/heads/main.zip"
CONFIRM_TOKEN = "UPDATE_BUNDLED"

# Desktop shell updates require a new exe. This action updates Memo services only.
ALLOWED_DIRS = ("memo", "scripts", "dashboard/dist")
ALLOWED_FILES = (
    "start_all.bat",
    "stop_all.bat",
    "upgrade.bat",
    "install.bat",
    "requirements.txt",
    "pyproject.toml",
    "README.md",
    "CHANGELOG.md",
    "AGENT_PROMPT.md",
    "mcp_config.example.json",
)
PROTECTED_NAMES = {
    ".env",
    "data",
    "logs",
    "backups",
    "release",
    "install_output",
    ".git",
    ".venv",
    "node_modules",
}
PROTECTED_SUFFIXES = (".db", ".db-wal", ".db-shm", ".sqlite", ".sqlite3", ".log")


def _is_protected(path: Path) -> bool:
    lower_parts = {part.lower() for part in path.parts}
    if lower_parts & PROTECTED_NAMES:
        return True
    name = path.name.lower()
    return name.startswith(".env") or name.endswith(PROTECTED_SUFFIXES)


def _find_source_root(extracted: Path) -> Path:
    candidates = [extracted, *[p for p in extracted.iterdir() if p.is_dir()]]
    for candidate in candidates:
        if (candidate / "memo").is_dir() and (candidate / "scripts").is_dir() and (candidate / "start_all.bat").exists():
            return candidate
    raise RuntimeError("下载包不是有效的 Memo 源码：缺少 memo/scripts/start_all.bat")


def _copy_tree(source: Path, target: Path) -> int:
    copied = 0
    if not source.exists():
        return copied
    for item in source.rglob("*"):
        relative = item.relative_to(source)
        destination = target / relative
        if _is_protected(relative):
            continue
        if item.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, destination)
        copied += 1
    return copied


def overlay_runtime(source_root: Path, target_root: Path) -> dict:
    target_root = target_root.resolve()
    source_root = source_root.resolve()
    copied = 0
    for relative_dir in ALLOWED_DIRS:
        source = source_root / Path(relative_dir)
        target = target_root / Path(relative_dir)
        copied += _copy_tree(source, target)
    copied_files = []
    for filename in ALLOWED_FILES:
        source = source_root / filename
        if not source.exists() or _is_protected(Path(filename)):
            continue
        target = target_root / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied += 1
        copied_files.append(filename)
    return {
        "target_root": str(target_root),
        "copied_count": copied,
        "copied_top_level_files": copied_files,
        "protected": ["data/", ".env*", "*.db", "*-wal", "*-shm", "logs/", "backups/", "desktop/"],
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--target-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--archive-url", default=DEFAULT_ARCHIVE_URL)
    parser.add_argument("--source-zip", default="", help="Local zip for tests/offline update")
    args = parser.parse_args()

    if not args.apply or args.confirm != CONFIRM_TOKEN:
        print(json.dumps({
            "ok": False,
            "dry_run": True,
            "message": f"真实更新必须使用 --apply --confirm {CONFIRM_TOKEN}",
            "target_root": str(Path(args.target_root).resolve()),
            "archive_url": args.archive_url,
        }, ensure_ascii=False))
        return 2

    target_root = Path(args.target_root).resolve()
    if not (target_root / "memo").is_dir() or not (target_root / "scripts").is_dir():
        raise RuntimeError(f"目标目录不是有效 Memo runtime: {target_root}")

    with tempfile.TemporaryDirectory(prefix="memo-runtime-update-") as temp_dir:
        temp = Path(temp_dir)
        archive = temp / "memo-main.zip"
        if args.source_zip:
            shutil.copy2(Path(args.source_zip).resolve(), archive)
        else:
            request = urllib.request.Request(args.archive_url, headers={"User-Agent": "Memo-Desktop-Companion"})
            with urllib.request.urlopen(request, timeout=120) as response, archive.open("wb") as output:
                shutil.copyfileobj(response, output)
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(temp / "extracted")
        source_root = _find_source_root(temp / "extracted")
        result = overlay_runtime(source_root, target_root)
        result.update({"ok": True, "mode": "bundled_archive", "archive_url": args.archive_url})
        print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
