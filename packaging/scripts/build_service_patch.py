"""Build an immutable, checksummed Memo service-only update archive."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT.parent / "Memo_Runtime_Optimization"
DEFAULT_OUTPUT = ROOT / "artifacts"
DIRECTORIES = ("memo", "scripts", "dashboard/dist")
FILES = ("start_all.bat", "stop_all.bat", "requirements.txt", "pyproject.toml", ".env.example", "mcp_config.example.json", "README.md")
FORBIDDEN_PARTS = {"data", "logs", "backups", ".venv", "node_modules", "release", "install_output", "reports", "__pycache__"}
FORBIDDEN_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".log", ".pyc", ".pem", ".key"}
FIXED_ZIP_TIME = (2026, 1, 1, 0, 0, 0)


def git_output(source: Path, *args: str) -> str:
    run = subprocess.run(["git", "-C", str(source), *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    if run.returncode != 0:
        raise RuntimeError(run.stderr or "Git command failed")
    return run.stdout.strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def allowed(path: Path, source: Path) -> bool:
    relative = path.relative_to(source)
    return not (
        {part.lower() for part in relative.parts} & FORBIDDEN_PARTS
        or path.name.startswith(".env") and path.name != ".env.example"
        or path.suffix.lower() in FORBIDDEN_SUFFIXES
    )


def collect_files(source: Path) -> list[tuple[Path, str]]:
    collected = []
    for relative in DIRECTORIES:
        folder = source / relative
        if not folder.is_dir():
            raise RuntimeError(f"Service patch source is missing: {folder}")
        for path in folder.rglob("*"):
            if path.is_file() and allowed(path, source):
                collected.append((path, f"app/{path.relative_to(source).as_posix()}"))
    for relative in FILES:
        path = source / relative
        if not path.is_file():
            raise RuntimeError(f"Service patch source is missing: {path}")
        collected.append((path, f"app/{PurePosixPath(relative).as_posix()}"))
    names = [name for _, name in collected]
    if len(names) != len(set(names)):
        raise RuntimeError("Service patch contains duplicate archive paths")
    return sorted(collected, key=lambda item: item[1])


def add_file(bundle: zipfile.ZipFile, source: Path, name: str) -> dict:
    digest = hashlib.sha256()
    info = zipfile.ZipInfo(name, date_time=FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    size = 0
    with source.open("rb") as input_stream, bundle.open(info, "w", force_zip64=True) as output_stream:
        while True:
            chunk = input_stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
            output_stream.write(chunk)
    return {"path": name.removeprefix("app/"), "size": size, "sha256": digest.hexdigest()}


def build(source: Path, output_dir: Path, version: str, allow_dirty: bool = False) -> dict:
    source = source.resolve()
    commit = git_output(source, "rev-parse", "HEAD")
    dirty = git_output(source, "status", "--porcelain", "--untracked-files=no")
    if dirty and not allow_dirty:
        raise RuntimeError("Memo source worktree has tracked changes; commit before building a release patch")
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"Memo-Service-{version}.zip"
    temporary = output.with_suffix(".zip.tmp")
    if temporary.exists():
        temporary.unlink()
    entries = []
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as bundle:
        for path, name in collect_files(source):
            entries.append(add_file(bundle, path, name))
        patch_manifest = {
            "schemaVersion": 2,
            "kind": "full",
            "serviceVersion": version,
            "sourceCommit": commit,
            "files": entries,
            "targetFiles": {row["path"]: row["sha256"] for row in entries},
        }
        manifest_info = zipfile.ZipInfo("service-patch-manifest.json", date_time=FIXED_ZIP_TIME)
        manifest_info.compress_type = zipfile.ZIP_DEFLATED
        manifest_info.external_attr = 0o644 << 16
        bundle.writestr(manifest_info, json.dumps(patch_manifest, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(output)
    published = {
        "schemaVersion": 2,
        "version": version,
        "sourceCommit": commit,
        "name": output.name,
        "size": output.stat().st_size,
        "sha256": sha256_file(output),
        "fileCount": len(entries),
    }
    sidecar = output.with_suffix(".manifest.json")
    sidecar.write_text(json.dumps(published, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    latest = output_dir / "Memo-Service-latest.zip"
    if latest.exists():
        latest.unlink()
    try:
        os.link(output, latest)
    except OSError:
        latest.write_bytes(output.read_bytes())
    print(f"Service patch ready: {output} ({published['size'] / 1024 / 1024:.2f} MB)")
    return published


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", default=os.getenv("MEMO_SOURCE_ROOT", str(DEFAULT_SOURCE)))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--version", default="")
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args()
    source = Path(args.source_root)
    version = args.version
    if not version:
        version = json.loads((source / "package.json").read_text(encoding="utf-8"))["version"]
    build(source, Path(args.output_dir), version, allow_dirty=args.allow_dirty)


if __name__ == "__main__":
    main()
