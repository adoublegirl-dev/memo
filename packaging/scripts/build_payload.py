"""Create a clean Memo service payload for the full installer.

Copies only explicit program files from Memo_V0.1.0. User data and secrets are
never discovered by scanning/copying broad directories.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

INSTALLER_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_ROOT = INSTALLER_ROOT.parent / "Memo_Runtime_Optimization"
PAYLOAD = INSTALLER_ROOT / "payload" / "app"

DIRECTORIES = ("memo", "scripts", "dashboard/dist")
FILES = ("start_all.bat", "stop_all.bat", "requirements.txt", "pyproject.toml", ".env.example", "mcp_config.example.json", "README.md")
EXCLUDED_DIRS = {"__pycache__", "data", "logs", "backups", ".venv", "node_modules", "release", "install_output", "reports"}
EXCLUDED_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".log", ".pyc"}


def ignore(_folder: str, names: list[str]) -> set[str]:
    return {name for name in names if name in EXCLUDED_DIRS or name.startswith(".env") or Path(name).suffix.lower() in EXCLUDED_SUFFIXES}


def git_output(source_root: Path, *args: str) -> str:
    run = subprocess.run(
        ["git", "-C", str(source_root), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    if run.returncode != 0:
        raise RuntimeError(run.stderr or f"Git command failed in {source_root}")
    return run.stdout.strip()


def build(source_root: Path, allow_dirty: bool = False) -> dict:
    source_root = source_root.resolve()
    commit = git_output(source_root, "rev-parse", "HEAD")
    dirty = git_output(source_root, "status", "--porcelain", "--untracked-files=no")
    if dirty and not allow_dirty:
        raise RuntimeError("Memo source worktree has tracked changes. Commit or explicitly use --allow-dirty before packaging.")
    if PAYLOAD.exists():
        shutil.rmtree(PAYLOAD)
    PAYLOAD.mkdir(parents=True)
    for relative in DIRECTORIES:
        source = source_root / relative
        destination = PAYLOAD / relative
        if not source.exists():
            raise RuntimeError(f"Required payload directory missing: {source}")
        shutil.copytree(source, destination, ignore=ignore)
    for relative in FILES:
        source = source_root / relative
        if not source.exists():
            raise RuntimeError(f"Required payload file missing: {source}")
        destination = PAYLOAD / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    manifest = {
        "schemaVersion": 1,
        "sourceCommit": commit,
        "dirtySource": bool(dirty),
    }
    (PAYLOAD / "memo-build-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Payload created from {commit[:12]}: {PAYLOAD}")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", default=os.getenv("MEMO_SOURCE_ROOT", str(DEFAULT_SOURCE_ROOT)))
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args()
    build(Path(args.source_root), allow_dirty=args.allow_dirty)


if __name__ == "__main__":
    main()
