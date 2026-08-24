"""Apply, rollback and finalize immutable Memo service patches.

This runner only replaces the program app directory. It never reads, copies,
removes or restores Memo databases, WAL/SHM files, .env or user uploads.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
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
TRANSACTION_NAME = "service-update-transaction.json"


def transaction_file(paths: PatchPaths) -> Path:
    return paths.app_root.parent / TRANSACTION_NAME


def write_json_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def transaction_child(paths: PatchPaths, raw: str, prefixes: tuple[str, ...]) -> Path | None:
    if not raw:
        return None
    candidate = Path(raw)
    program_root = paths.app_root.parent.resolve()
    if candidate.parent.resolve() != program_root or not candidate.name.startswith(prefixes):
        raise RuntimeError(f"Unsafe service update transaction path: {candidate}")
    return candidate


def begin_transaction(paths: PatchPaths, operation: str, backup: Path, staging: Path, payload: Path | None = None) -> None:
    state_path = transaction_file(paths)
    if state_path.exists():
        raise RuntimeError("An unfinished service update transaction exists; recover it before applying another patch")
    write_json_atomic(state_path, {
        "schemaVersion": 1,
        "operation": operation,
        "phase": "prepared",
        "appRoot": str(paths.app_root),
        "backup": str(backup),
        "staging": str(staging),
        "payload": str(payload or ""),
    })


def set_transaction_phase(paths: PatchPaths, phase: str) -> None:
    state_path = transaction_file(paths)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["phase"] = phase
    write_json_atomic(state_path, state)


def clear_transaction(paths: PatchPaths) -> None:
    state_path = transaction_file(paths)
    if state_path.exists():
        state_path.unlink()


def release_runtime_locks(paths: PatchPaths) -> None:
    if os.name != "nt":
        return
    runtime_root = paths.app_root.parent / "runtime"
    if not (runtime_root / "python.exe").is_file():
        return
    quoted_root = str(runtime_root.resolve()).replace("'", "''")
    script = f"""
$root = [IO.Path]::GetFullPath('{quoted_root}')
$exclude = {os.getpid()}
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
  Where-Object {{ $_.ProcessId -ne $exclude -and $_.ExecutablePath -and [IO.Path]::GetFullPath($_.ExecutablePath).StartsWith($root, [StringComparison]::OrdinalIgnoreCase) }} |
  ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; Wait-Process -Id $_.ProcessId -Timeout 3 -ErrorAction SilentlyContinue }}
"""
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    try:
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-EncodedCommand", encoded], capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=25,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def rename_with_retry(source: Path, target: Path, paths: PatchPaths, attempts: int = 8) -> None:
    last_error = None
    for attempt in range(attempts):
        release_runtime_locks(paths)
        try:
            source.replace(target)
            return
        except PermissionError as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(min(0.35 * (attempt + 1), 1.5))
    raise RuntimeError(
        f"Memo程序目录仍被其他进程占用，已自动重试{attempts}次。"
        "请完全退出使用Memo MCP的Agent后重试。"
        f"原始错误：{last_error}"
    ) from last_error


def remove_tree_with_retry(target: Path, paths: PatchPaths, attempts: int = 8) -> None:
    last_error = None
    for attempt in range(attempts):
        release_runtime_locks(paths)
        try:
            shutil.rmtree(target)
            return
        except FileNotFoundError:
            return
        except PermissionError as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(min(0.35 * (attempt + 1), 1.5))
    raise RuntimeError(f"Unable to remove locked Memo program directory after {attempts} attempts: {last_error}") from last_error


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def managed_relative(name: str) -> Path:
    pure = PurePosixPath(name)
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        raise RuntimeError(f"Unsafe service patch path: {name}")
    relative = Path(*pure.parts)
    if set(part.lower() for part in relative.parts) & FORBIDDEN_PARTS:
        raise RuntimeError(f"Forbidden service patch path: {relative}")
    if relative.name == "memo-install-manifest.json":
        raise RuntimeError("The local install manifest cannot be patched")
    if relative.name.startswith(".env") and relative.name != ".env.example":
        raise RuntimeError(f"Forbidden service patch config: {relative}")
    if relative.suffix.lower() in FORBIDDEN_SUFFIXES:
        raise RuntimeError(f"Forbidden service patch file: {relative}")
    return relative


def safe_relative(name: str) -> Path | None:
    pure = PurePosixPath(name)
    if pure.is_absolute() or ".." in pure.parts:
        raise RuntimeError(f"Unsafe service patch path: {name}")
    if name == "service-patch-manifest.json":
        return None
    if not pure.parts or pure.parts[0] != "app":
        raise RuntimeError(f"Unexpected service patch root: {name}")
    if len(pure.parts) == 1:
        return None
    return managed_relative(PurePosixPath(*pure.parts[1:]).as_posix())


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
            name = managed_relative(str(row.get("path") or "")).as_posix()
            if name in expected_files:
                raise RuntimeError(f"Duplicate service patch manifest path: {name}")
            expected_files[name] = row
        seen = set()
        for info in bundle.infolist():
            relative = safe_relative(info.filename)
            if relative is None:
                continue
            name = relative.as_posix()
            if name in seen:
                raise RuntimeError(f"Duplicate service patch archive path: {name}")
            seen.add(name)
            if name not in expected_files:
                raise RuntimeError(f"Service patch contains an undeclared file: {name}")
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


def validate_target_files(value) -> dict[str, str]:
    if not isinstance(value, dict) or not value:
        raise RuntimeError("Delta patch targetFiles baseline is missing")
    validated = {}
    for raw_path, raw_digest in value.items():
        relative = managed_relative(str(raw_path)).as_posix()
        digest = str(raw_digest or "").lower()
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise RuntimeError(f"Invalid target file SHA-256: {relative}")
        validated[relative] = digest
    return validated


def remove_bytecode_caches(root: Path) -> None:
    for folder in sorted((path for path in root.rglob("__pycache__") if path.is_dir()), key=lambda item: len(item.parts), reverse=True):
        shutil.rmtree(folder, ignore_errors=True)
    for path in root.rglob("*.pyc"):
        try:
            path.unlink()
        except OSError:
            pass


def extract_delta_payload(archive: Path, payload_root: Path, manifest: dict) -> dict[str, dict]:
    expected = {}
    for row in manifest.get("files") or []:
        relative = managed_relative(str(row.get("path") or "")).as_posix()
        if relative in expected:
            raise RuntimeError(f"Duplicate delta manifest path: {relative}")
        expected[relative] = row
    seen = set()
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            relative = safe_relative(info.filename)
            if relative is None:
                continue
            name = relative.as_posix()
            if name in seen:
                raise RuntimeError(f"Duplicate delta archive path: {name}")
            seen.add(name)
            if name not in expected:
                raise RuntimeError(f"Delta archive contains an undeclared file: {name}")
            if info.is_dir():
                continue
            destination = payload_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(info, "r") as source, destination.open("wb") as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)
    if seen != set(expected):
        missing = sorted(set(expected) - seen)
        raise RuntimeError(f"Delta archive is missing declared files: {', '.join(missing[:5])}")
    for name, row in expected.items():
        path = payload_root / Path(*PurePosixPath(name).parts)
        digest = str(row.get("sha256") or "").lower()
        if not path.is_file() or path.stat().st_size != int(row.get("size", -1)) or sha256_file(path) != digest:
            raise RuntimeError(f"Delta file verification failed: {name}")
    return expected


def py_compile_smoke(app_root: Path) -> None:
    targets = [app_root / "scripts" / "memo_dashboard.py", app_root / "memo" / "core" / "engine.py"]
    missing = [str(path) for path in targets if not path.is_file()]
    if missing:
        raise RuntimeError(f"Service patch smoke targets missing: {', '.join(missing)}")
    compile_script = (
        "import pathlib,sys; root=pathlib.Path(sys.argv[1]); "
        "files=[p for p in root.rglob('*.py') if '__pycache__' not in p.parts]; "
        "[compile(p.read_text(encoding='utf-8-sig'), str(p), 'exec') for p in files]; "
        "print(len(files))"
    )
    run = subprocess.run(
        [sys.executable, "-c", compile_script, str(app_root)],
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
        target_files = validate_target_files(manifest.get("targetFiles") or {
            str(row.get("path")): str(row.get("sha256"))
            for row in (manifest.get("files") or [])
            if row.get("path") and row.get("sha256")
        })
        declared_files = {
            managed_relative(str(row.get("path") or "")).as_posix(): str(row.get("sha256") or "").lower()
            for row in (manifest.get("files") or [])
        }
        if target_files != declared_files:
            raise RuntimeError("Full service patch targetFiles baseline does not match its payload")
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    begin_transaction(paths, "full", backup, staging)
    try:
        if paths.app_root.exists():
            rename_with_retry(paths.app_root, backup, paths)
        set_transaction_phase(paths, "backup-created")
        rename_with_retry(staging, paths.app_root, paths)
        set_transaction_phase(paths, "switched")
        install_manifest = {
            "schemaVersion": 2,
            "serviceVersion": manifest.get("serviceVersion", expected_version),
            "sourceCommit": manifest.get("sourceCommit", ""),
            "installedFiles": target_files,
        }
        paths.manifest.write_text(json.dumps(install_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        py_compile_smoke(paths.app_root)
        set_transaction_phase(paths, "applied")
    except Exception:
        if paths.app_root.exists():
            remove_tree_with_retry(paths.app_root, paths)
        if backup.exists():
            rename_with_retry(backup, paths.app_root, paths)
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        clear_transaction(paths)
        raise
    return {
        "ok": True,
        "serviceVersion": manifest.get("serviceVersion", expected_version),
        "sourceCommit": manifest.get("sourceCommit", ""),
        "backup": str(backup) if backup.exists() else "",
        "appRoot": str(paths.app_root),
    }


def apply_delta_patch(archive: Path, expected_sha256: str, expected_from: str, expected_to: str) -> dict:
    paths = patch_paths()
    if not archive.is_file():
        raise RuntimeError(f"Delta patch archive is missing: {archive}")
    if not expected_sha256 or sha256_file(archive) != expected_sha256.lower():
        raise RuntimeError("Delta patch archive SHA-256 verification failed")
    with zipfile.ZipFile(archive) as bundle:
        manifest = load_inner_manifest(bundle)
    if manifest.get("kind") != "delta" or int(manifest.get("schemaVersion") or 0) < 2:
        raise RuntimeError("Artifact is not a supported delta patch")
    from_version = str(manifest.get("fromVersion") or "")
    to_version = str(manifest.get("toVersion") or "")
    if from_version != expected_from or to_version != expected_to:
        raise RuntimeError(f"Delta version mismatch: {from_version}->{to_version} != {expected_from}->{expected_to}")
    try:
        local_manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError("Local installedFiles baseline is missing; use the full service package once") from exc
    if str(local_manifest.get("serviceVersion") or "") != from_version:
        raise RuntimeError(f"Installed service version is not the delta base: {local_manifest.get('serviceVersion')} != {from_version}")
    installed_files = local_manifest.get("installedFiles")
    if not isinstance(installed_files, dict) or not installed_files:
        raise RuntimeError("Local installedFiles baseline is missing; use the full service package once")
    installed_files = {str(path): str(digest).lower() for path, digest in installed_files.items()}
    target_files = validate_target_files(manifest.get("targetFiles"))

    program_root = paths.app_root.parent
    staging = program_root / f"app.update-{uuid.uuid4().hex}"
    payload_root = program_root / f".patch-payload-{uuid.uuid4().hex}"
    backup = program_root / f"app.previous-{uuid.uuid4().hex}"
    skipped_deletes = []
    try:
        expected_rows = extract_delta_payload(archive, payload_root, manifest)
        if not paths.app_root.is_dir():
            raise RuntimeError("Installed Memo app directory is missing")
        shutil.copytree(paths.app_root, staging)
        remove_bytecode_caches(staging)

        for name, row in expected_rows.items():
            relative = Path(*PurePosixPath(name).parts)
            current = paths.app_root / relative
            old_digest = row.get("oldSha256")
            new_digest = str(row.get("sha256") or "").lower()
            baseline_digest = installed_files.get(name)
            if old_digest:
                old_digest = str(old_digest).lower()
                if baseline_digest != old_digest or not current.is_file() or sha256_file(current) != old_digest:
                    raise RuntimeError(f"Delta base file mismatch, refusing overwrite: {name}")
            elif baseline_digest:
                raise RuntimeError(f"Delta expected a new path but baseline already owns it: {name}")
            elif current.exists() and (not current.is_file() or sha256_file(current) != new_digest):
                raise RuntimeError(f"Unmanaged local path conflicts with delta addition: {name}")
            destination = staging / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(payload_root / relative, destination)

        seen_deletes = set()
        for row in manifest.get("deletes") or []:
            name = managed_relative(str(row.get("path") or "")).as_posix()
            if name in seen_deletes:
                raise RuntimeError(f"Duplicate delta delete path: {name}")
            seen_deletes.add(name)
            old_digest = str(row.get("oldSha256") or "").lower()
            if len(old_digest) != 64:
                raise RuntimeError(f"Delta delete is missing old SHA-256: {name}")
            candidate = staging / Path(*PurePosixPath(name).parts)
            if installed_files.get(name) != old_digest:
                skipped_deletes.append({"path": name, "reason": "baseline_mismatch"})
                continue
            if not candidate.exists():
                skipped_deletes.append({"path": name, "reason": "already_missing"})
                continue
            if not candidate.is_file() or sha256_file(candidate) != old_digest:
                skipped_deletes.append({"path": name, "reason": "local_file_changed"})
                continue
            candidate.unlink()

        for name, digest in target_files.items():
            candidate = staging / Path(*PurePosixPath(name).parts)
            if not candidate.is_file() or sha256_file(candidate) != digest:
                raise RuntimeError(f"Delta target baseline verification failed: {name}")
        if not (staging / "start_all.bat").is_file() or not (staging / "memo").is_dir():
            raise RuntimeError("Delta target is missing required Memo app files")

        begin_transaction(paths, "delta", backup, staging, payload_root)
        try:
            if paths.app_root.exists():
                rename_with_retry(paths.app_root, backup, paths)
            set_transaction_phase(paths, "backup-created")
            rename_with_retry(staging, paths.app_root, paths)
            set_transaction_phase(paths, "switched")
            paths.manifest.write_text(
                json.dumps(
                    {
                        "schemaVersion": 2,
                        "serviceVersion": to_version,
                        "sourceCommit": manifest.get("toCommit", ""),
                        "installedFiles": target_files,
                        "skippedDeletes": skipped_deletes,
                    },
                    ensure_ascii=False,
                    indent=2,
                ) + "\n",
                encoding="utf-8",
            )
            py_compile_smoke(paths.app_root)
            set_transaction_phase(paths, "applied")
        except Exception:
            if paths.app_root.exists():
                remove_tree_with_retry(paths.app_root, paths)
            if backup.exists():
                rename_with_retry(backup, paths.app_root, paths)
            clear_transaction(paths)
            raise
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        if payload_root.exists():
            shutil.rmtree(payload_root, ignore_errors=True)
    return {
        "ok": True,
        "kind": "delta",
        "fromVersion": from_version,
        "serviceVersion": to_version,
        "sourceCommit": manifest.get("toCommit", ""),
        "backup": str(backup) if backup.exists() else "",
        "appRoot": str(paths.app_root),
        "skippedDeletes": skipped_deletes,
    }


def rollback(backup: Path) -> dict:
    paths = patch_paths()
    backup = transaction_child(paths, str(backup), ("app.previous-",))
    if backup is None or not backup.is_dir():
        raise RuntimeError(f"Service rollback directory is missing: {backup}")
    failed = paths.app_root.parent / f"app.failed-{uuid.uuid4().hex}"
    if paths.app_root.exists():
        rename_with_retry(paths.app_root, failed, paths)
    rename_with_retry(backup, paths.app_root, paths)
    if failed.exists():
        shutil.rmtree(failed, ignore_errors=True)
    clear_transaction(paths)
    return {"ok": True, "rolledBack": True, "appRoot": str(paths.app_root)}


def finalize(backup: Path) -> dict:
    # Keep the program backup for manual recovery. It contains code only; no
    # database or .env is ever stored here. Finalize only clears our own marker.
    paths = patch_paths()
    backup_text = str(backup)
    validated = transaction_child(paths, backup_text, ("app.previous-",)) if backup_text not in ("", ".") else None
    state_path = transaction_file(paths)
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        recorded = transaction_child(paths, str(state.get("backup") or ""), ("app.previous-",))
        if validated is None or recorded != validated:
            raise RuntimeError("Finalize backup does not match the active service transaction")
        clear_transaction(paths)
    return {"ok": True, "backupKept": str(validated) if validated and validated.exists() else ""}


def recover() -> dict:
    """Conservatively restore an update interrupted before health verification."""
    paths = patch_paths()
    state_path = transaction_file(paths)
    if not state_path.exists():
        return {"ok": True, "recovered": False, "residuals": []}
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Service transaction marker is unreadable; refusing automatic cleanup: {state_path}") from exc
    if Path(str(state.get("appRoot") or "")).resolve() != paths.app_root.resolve():
        raise RuntimeError("Service transaction appRoot mismatch; refusing automatic recovery")
    backup = transaction_child(paths, str(state.get("backup") or ""), ("app.previous-",))
    staging = transaction_child(paths, str(state.get("staging") or ""), ("app.update-",))
    payload = transaction_child(paths, str(state.get("payload") or ""), (".patch-payload-",))
    phase = str(state.get("phase") or "")
    residuals = [str(item) for item in (staging, payload) if item and item.exists()]
    if backup and backup.is_dir():
        if paths.app_root.exists():
            quarantine = paths.app_root.parent / f"app.recovery-unverified-{uuid.uuid4().hex}"
            rename_with_retry(paths.app_root, quarantine, paths)
            residuals.append(str(quarantine))
        rename_with_retry(backup, paths.app_root, paths)
        clear_transaction(paths)
        return {"ok": True, "recovered": True, "phase": phase, "appRoot": str(paths.app_root), "residuals": residuals}
    if phase == "prepared" and paths.app_root.is_dir():
        clear_transaction(paths)
        return {"ok": True, "recovered": True, "phase": phase, "appRoot": str(paths.app_root), "residuals": residuals}
    raise RuntimeError("Interrupted service update has no safe rollback directory; no automatic deletion was performed")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", choices=("apply", "apply-delta", "rollback", "finalize", "recover"), required=True)
    parser.add_argument("--archive", default="")
    parser.add_argument("--sha256", default="")
    parser.add_argument("--version", default="")
    parser.add_argument("--from-version", default="")
    parser.add_argument("--backup", default="")
    parser.add_argument("--user-root", default="")
    args = parser.parse_args()
    if args.user_root:
        os.environ["MEMO_USER_ROOT"] = args.user_root
    try:
        if args.action == "apply":
            result = apply_patch(Path(args.archive), args.sha256, args.version)
        elif args.action == "apply-delta":
            result = apply_delta_patch(Path(args.archive), args.sha256, args.from_version, args.version)
        elif args.action == "rollback":
            result = rollback(Path(args.backup))
        elif args.action == "finalize":
            result = finalize(Path(args.backup))
        else:
            result = recover()
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
