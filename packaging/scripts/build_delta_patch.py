"""Build a deterministic from->to Memo service delta.

Release builds should compare two immutable full Service Patch ZIPs, not Git
working trees. This guarantees oldSha256/newSha256 exactly match bytes users
installed even when Windows autocrlf or build steps rewrite files. Git refs are
kept as a development convenience only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT.parent / "Memo_Runtime_Optimization"
DEFAULT_OUTPUT = ROOT / "artifacts" / "service"
DIRECTORIES = ("memo", "scripts", "dashboard/dist")
FILES = ("start_all.bat", "stop_all.bat", "requirements.txt", "pyproject.toml", ".env.example", "mcp_config.example.json", "README.md")
FORBIDDEN_PARTS = {"data", "logs", "backups", ".venv", "node_modules", "release", "install_output", "reports", "__pycache__"}
FORBIDDEN_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".log", ".pyc", ".pem", ".key"}
FIXED_ZIP_TIME = (2026, 1, 1, 0, 0, 0)


def run_git(source: Path, *args: str, text: bool = False):
    run = subprocess.run(
        ["git", "-C", str(source), *args], capture_output=True, text=text,
        encoding="utf-8" if text else None, errors="replace" if text else None, timeout=120,
    )
    if run.returncode != 0:
        detail = run.stderr if text else run.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(detail or f"git {' '.join(args)} failed")
    return run.stdout


def resolve_commit(source: Path, ref: str) -> str:
    return str(run_git(source, "rev-parse", f"{ref}^{{commit}}", text=True)).strip()


def allowed_relative(value: str) -> bool:
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        return False
    if set(part.lower() for part in relative.parts) & FORBIDDEN_PARTS:
        return False
    if relative.name.startswith(".env") and relative.name != ".env.example":
        return False
    if relative.suffix.lower() in FORBIDDEN_SUFFIXES:
        return False
    return value in FILES or any(value == root or value.startswith(f"{root}/") for root in DIRECTORIES)


def tree_files(source: Path, commit: str) -> dict[str, str]:
    raw = run_git(source, "ls-tree", "-r", "-z", "--full-tree", commit, "--", *DIRECTORIES, *FILES)
    files = {}
    for record in raw.split(b"\0"):
        if not record:
            continue
        metadata, raw_path = record.split(b"\t", 1)
        _mode, kind, blob = metadata.decode("ascii").split()
        path = raw_path.decode("utf-8", errors="surrogateescape")
        if kind == "blob" and allowed_relative(path):
            files[path] = blob
    return dict(sorted(files.items()))


def blob_bytes(source: Path, blob: str) -> bytes:
    return bytes(run_git(source, "cat-file", "blob", blob))


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_zip_entry(bundle: zipfile.ZipFile, name: str, content: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    bundle.writestr(info, content)


def package_contents(archive: Path) -> tuple[dict[str, bytes], dict]:
    if not archive.is_file():
        raise RuntimeError(f"Full service package is missing: {archive}")
    with zipfile.ZipFile(archive) as bundle:
        try:
            manifest = json.loads(bundle.read("service-patch-manifest.json").decode("utf-8"))
        except (KeyError, UnicodeDecodeError, ValueError) as exc:
            raise RuntimeError(f"Invalid full service package manifest: {archive}") from exc
        if manifest.get("kind") not in (None, "full"):
            raise RuntimeError(f"Expected a full service package, got {manifest.get('kind')}: {archive}")
        rows = manifest.get("files") or []
        declared = {}
        for row in rows:
            name = str(row.get("path") or "")
            if not allowed_relative(name) or name in declared:
                raise RuntimeError(f"Unsafe or duplicate full package path: {name}")
            declared[name] = row
        contents = {}
        for info in bundle.infolist():
            if info.filename == "service-patch-manifest.json" or info.is_dir():
                continue
            pure = PurePosixPath(info.filename)
            if not pure.parts or pure.parts[0] != "app":
                raise RuntimeError(f"Unexpected full package entry: {info.filename}")
            name = PurePosixPath(*pure.parts[1:]).as_posix()
            if name not in declared or name in contents:
                raise RuntimeError(f"Undeclared or duplicate full package entry: {name}")
            content = bundle.read(info)
            row = declared[name]
            if len(content) != int(row.get("size", -1)) or sha256_bytes(content) != str(row.get("sha256") or "").lower():
                raise RuntimeError(f"Full package payload verification failed: {name}")
            contents[name] = content
        if set(contents) != set(declared):
            raise RuntimeError(f"Full package file list mismatch: {archive}")
    return dict(sorted(contents.items())), manifest


def build_content_delta(
    old_content: dict[str, bytes], new_content: dict[str, bytes], output_dir: Path,
    from_version: str, to_version: str, from_commit: str = "", to_commit: str = "",
    allow_large_delete_set: bool = False,
) -> dict:
    if not old_content or not new_content:
        raise RuntimeError("Both releases must contain a complete Memo service tree")
    if any(not allowed_relative(name) for name in [*old_content, *new_content]):
        raise RuntimeError("Release content contains a forbidden managed path")
    changed_paths = [path for path in sorted(new_content) if old_content.get(path) != new_content[path]]
    deleted_paths = [path for path in sorted(old_content) if path not in new_content]
    delete_limit = max(20, int(len(old_content) * 0.10))
    if len(deleted_paths) > delete_limit and not allow_large_delete_set:
        raise RuntimeError(
            f"Refusing suspicious delete set: {len(deleted_paths)} files exceeds conservative limit {delete_limit}. "
            "Review the diff and pass --allow-large-delete-set only when intentional."
        )

    file_rows = []
    for path in changed_paths:
        content = new_content[path]
        file_rows.append({
            "path": path, "size": len(content), "sha256": sha256_bytes(content),
            "oldSha256": sha256_bytes(old_content[path]) if path in old_content else None,
        })
    delete_rows = [{"path": path, "oldSha256": sha256_bytes(old_content[path])} for path in deleted_paths]
    target_files = {path: sha256_bytes(new_content[path]) for path in sorted(new_content)}

    output_dir.mkdir(parents=True, exist_ok=True)
    safe_from = from_version.replace("/", "-")
    safe_to = to_version.replace("/", "-")
    output = output_dir / f"Memo-Service-{safe_from}_to_{safe_to}.zip"
    temporary = output.with_suffix(".zip.tmp")
    if temporary.exists():
        temporary.unlink()
    manifest = {
        "schemaVersion": 2, "kind": "delta", "fromVersion": from_version, "toVersion": to_version,
        "fromCommit": from_commit, "toCommit": to_commit, "files": file_rows,
        "deletes": delete_rows, "targetFiles": target_files,
    }
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as bundle:
        for row in file_rows:
            write_zip_entry(bundle, f"app/{row['path']}", new_content[row["path"]])
        write_zip_entry(bundle, "service-patch-manifest.json", (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    temporary.replace(output)
    published = {
        "schemaVersion": 2, "kind": "delta", "from": from_version, "to": to_version,
        "fromCommit": from_commit, "toCommit": to_commit, "name": output.name,
        "size": output.stat().st_size, "sha256": sha256_file(output),
        "files": len(file_rows), "deletes": len(delete_rows),
    }
    output.with_suffix(".manifest.json").write_text(json.dumps(published, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Delta patch ready: {output} ({published['size'] / 1024:.1f} KB, {len(file_rows)} files, {len(delete_rows)} deletes)")
    return published


def build(source: Path, output_dir: Path, from_ref: str, to_ref: str, from_version: str, to_version: str, allow_large_delete_set: bool = False) -> dict:
    """Development helper using raw Git blob bytes; release builds use packages."""
    source = source.resolve()
    from_commit = resolve_commit(source, from_ref)
    to_commit = resolve_commit(source, to_ref)
    old_tree = tree_files(source, from_commit)
    new_tree = tree_files(source, to_commit)
    old_content = {path: blob_bytes(source, blob) for path, blob in old_tree.items()}
    new_content = {path: blob_bytes(source, blob) for path, blob in new_tree.items()}
    return build_content_delta(old_content, new_content, output_dir, from_version, to_version, from_commit, to_commit, allow_large_delete_set)


def build_from_packages(from_package: Path, to_package: Path, output_dir: Path, from_version: str = "", to_version: str = "", allow_large_delete_set: bool = False) -> dict:
    old_content, old_manifest = package_contents(from_package)
    new_content, new_manifest = package_contents(to_package)
    actual_from = str(old_manifest.get("serviceVersion") or "")
    actual_to = str(new_manifest.get("serviceVersion") or "")
    if from_version and from_version != actual_from:
        raise RuntimeError(f"Old package version mismatch: {actual_from} != {from_version}")
    if to_version and to_version != actual_to:
        raise RuntimeError(f"New package version mismatch: {actual_to} != {to_version}")
    if not actual_from or not actual_to:
        raise RuntimeError("Full service packages must declare serviceVersion")
    return build_content_delta(
        old_content, new_content, output_dir, actual_from, actual_to,
        str(old_manifest.get("sourceCommit") or ""), str(new_manifest.get("sourceCommit") or ""), allow_large_delete_set,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", default=str(DEFAULT_SOURCE))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--from-ref")
    parser.add_argument("--to-ref")
    parser.add_argument("--from-package")
    parser.add_argument("--to-package")
    parser.add_argument("--from-version", default="")
    parser.add_argument("--to-version", default="")
    parser.add_argument("--allow-large-delete-set", action="store_true")
    args = parser.parse_args()
    if args.from_package or args.to_package:
        if not args.from_package or not args.to_package:
            parser.error("--from-package and --to-package must be provided together")
        build_from_packages(
            Path(args.from_package), Path(args.to_package), Path(args.output_dir),
            args.from_version, args.to_version, args.allow_large_delete_set,
        )
    else:
        if not all((args.from_ref, args.to_ref, args.from_version, args.to_version)):
            parser.error("Git mode requires --from-ref, --to-ref, --from-version and --to-version")
        build(
            Path(args.source_root), Path(args.output_dir), args.from_ref, args.to_ref,
            args.from_version, args.to_version, args.allow_large_delete_set,
        )


if __name__ == "__main__":
    main()
