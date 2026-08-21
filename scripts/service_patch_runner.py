"""Apply, rollback and finalize immutable Memo service patches.

This runner only replaces the program app directory. It never reads, copies,
removes or restores Memo databases, WAL/SHM files, .env or user uploads.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


@dataclass(frozen=True)
class PatchPaths:
    user_root: Path
    app_root: Path
    manifest: Path


def patch_paths() -> PatchPaths:
    user_root = Path(os.environ.get("MEMO_USER_ROOT") or Path.home() / "AppData" / "Local" / "Memo")
    app_root = user_root / "Programs" / "Memo" / "app"
    return PatchPaths(user_root=user_root, app_root=app_root, manifest=app_root / "memo-install-manifest.json")

FORBIDDEN_PARTS = {"data", "logs", "backups", ".venv", "node_modules", "release", "install_output", "reports", "__pycache__"}
FORBIDDEN_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".log", ".pyc", ".pem", ".key"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_relative(name: str) -> Path | None:
    pure = PurePosixPath(name)
    if pure.is_absolute() or ".." in pure.parts:
        raise RuntimeError(f"Unsafe service patch path: {name}")
    if name == "service-patch-manifest.json":
        return None
    if not pure.parts or pure.parts[0] != "app":
        raise RuntimeError(f"Unexpected service patch root: {name}")
    relative = Path(*pure.parts[1:])
    if not relative.parts:
        return None
    if set(part.lower() for part in relative.parts) & FORBIDDEN_PARTS:
        raise RuntimeError(f"Forbidden service patch path: {relative}")
    if relative.name.startswith(".env") and relative.name != ".env.example":
        raise RuntimeError(f"Forbidden service patch config: {relative}")
    if relative.suffix.lower() in FORBIDDEN_SUFFIXES:
        raise RuntimeError(f"Forbidden service patch file: {relative}")
    return relative


def load_inner_manifest(bundle: zipfile.ZipFile) -> dict:
    try:
        return json.loads(bundle.read("service-patch-manifest.json").decode("utf-8"))
    except (KeyError, UnicodeDecodeError, ValueError) as exc:
        raise RuntimeError("Service patch manifest is missing or invalid") from exc


def extract_and_verify(archive: Path, staging: Path, expected_version: str) -> dict:
    expected_files = {}
    with zipfile.ZipFile(archive) as bundle:
        manifest = load_inner_manifest(bundle)
        if expected_version and manifest.get("serviceVersion") != expected_version:
            raise RuntimeError(
                f"Service patch version mismatch: {manifest.get('serviceVersion')} != {expected_version}"
            )
        for row in manifest.get("files") or []:
            expected_files[str(row.get("path") or "")] = row
        for info in bundle.infolist():
            relative = safe_relative(info.filename)
            if relative is None:
                continue
            destination = staging / relative
            if info.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(info, "r") as source, destination.open("wb") as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)
    if not (staging / "start_all.bat").is_file() or not (staging / "memo").is_dir():
        raise RuntimeError("Service patch is incomplete: required app files are missing")
    actual_files = [path for path in staging.rglob("*") if path.is_file()]
    if len(actual_files) != len(expected_files):
        raise RuntimeError(f"Service patch file count mismatch: {len(actual_files)} != {len(expected_files)}")
    for path in actual_files:
        relative = path.relative_to(staging).as_posix()
        expected = expected_files.get(relative)
        if not expected:
            raise RuntimeError(f"Service patch contains an undeclared file: {relative}")
        expected_size = expected.get("size")
        if expected_size is None or path.stat().st_size != int(expected_size) or sha256_file(path) != expected.get("sha256"):
            raise RuntimeError(f"Service patch file verification failed: {relative}")
    return manifest


def py_compile_smoke(app_root: Path) -> None:
    targets = [app_root / "scripts" / "memo_dashboard.py", app_root / "memo" / "core" / "engine.py"]
    missing = [str(path) for path in targets if not path.is_file()]
    if missing:
        raise RuntimeError(f"Service patch smoke targets missing: {', '.join(missing)}")
    compile_script = (
        "import pathlib,sys; "
        "[compile(p.read_text(encoding='utf-8-sig'), str(p), 'exec') "
        "for p in map(pathlib.Path, sys.argv[1:])]"
    )
    run = subprocess.run(
        [sys.executable, "-c", compile_script, *map(str, targets)],
        cwd=app_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    if run.returncode != 0:
        raise RuntimeError(run.stderr or run.stdout or "Service patch compile smoke failed")


def apply_patch(archive: Path, expected_sha256: str, expected_version: str) -> dict:
    paths = patch_paths()
    if not archive.is_file():
        raise RuntimeError(f"Service patch archive is missing: {archive}")
    if not expected_sha256 or sha256_file(archive) != expected_sha256.lower():
        raise RuntimeError("Service patch archive SHA-256 verification failed")
    program_root = paths.app_root.parent
    staging = program_root / f"app.update-{uuid.uuid4().hex}"
    backup = program_root / f"app.previous-{uuid.uuid4().hex}"
    staging.mkdir(parents=True)
    try:
        manifest = extract_and_verify(archive, staging, expected_version)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    if paths.app_root.exists():
        paths.app_root.replace(backup)
    try:
        staging.replace(paths.app_root)
        install_manifest = {
            "serviceVersion": manifest.get("serviceVersion", expected_version),
            "sourceCommit": manifest.get("sourceCommit", ""),
        }
        paths.manifest.write_text(json.dumps(install_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        py_compile_smoke(paths.app_root)
    except Exception:
        if paths.app_root.exists():
            shutil.rmtree(paths.app_root, ignore_errors=True)
        if backup.exists():
            backup.replace(paths.app_root)
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise
    return {
        "ok": True,
        "serviceVersion": manifest.get("serviceVersion", expected_version),
        "sourceCommit": manifest.get("sourceCommit", ""),
        "backup": str(backup) if backup.exists() else "",
        "appRoot": str(paths.app_root),
    }


def rollback(backup: Path) -> dict:
    paths = patch_paths()
    if not backup.is_dir():
        raise RuntimeError(f"Service rollback directory is missing: {backup}")
    failed = paths.app_root.parent / f"app.failed-{uuid.uuid4().hex}"
    if paths.app_root.exists():
        paths.app_root.replace(failed)
    backup.replace(paths.app_root)
    if failed.exists():
        shutil.rmtree(failed, ignore_errors=True)
    return {"ok": True, "rolledBack": True, "appRoot": str(paths.app_root)}


def finalize(backup: Path) -> dict:
    # Keep the most recent program backup for manual recovery. It contains code
    # only; no database or .env is ever stored here.
    if not backup:
        return {"ok": True, "backupKept": ""}
    return {"ok": True, "backupKept": str(backup) if backup.exists() else ""}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", choices=("apply", "rollback", "finalize"), required=True)
    parser.add_argument("--archive", default="")
    parser.add_argument("--sha256", default="")
    parser.add_argument("--version", default="")
    parser.add_argument("--backup", default="")
    parser.add_argument("--user-root", default="")
    args = parser.parse_args()
    if args.user_root:
        os.environ["MEMO_USER_ROOT"] = args.user_root
    try:
        if args.action == "apply":
            result = apply_patch(Path(args.archive), args.sha256, args.version)
        elif args.action == "rollback":
            result = rollback(Path(args.backup))
        else:
            result = finalize(Path(args.backup))
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
