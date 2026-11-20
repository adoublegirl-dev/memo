"""Idempotent full Memo installer runner.

This runner is launched by the packaged desktop companion. It copies an audited
payload to the user's program directory, preserves user data, writes only the
user's local config, and initializes/migrates the user's database.
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
from datetime import datetime
from pathlib import Path, PurePosixPath

THIS_DIR = Path(__file__).resolve().parent
INSTALLER_ROOT = THIS_DIR.parent
for import_root in (THIS_DIR, INSTALLER_ROOT):
    text = str(import_root)
    if text not in sys.path:
        sys.path.insert(0, text)

try:
    from .install_contract import SERVICE_VERSION, detect_state, ensure_user_dirs, install_paths, read_env, runtime_python_path, service_environment, write_user_config
except ImportError:  # direct script execution or embedded Python ._pth isolation
    from install_contract import SERVICE_VERSION, detect_state, ensure_user_dirs, install_paths, read_env, runtime_python_path, service_environment, write_user_config

PAYLOAD_APP = INSTALLER_ROOT / "payload" / "app"
PAYLOAD_RUNTIME = INSTALLER_ROOT / "runtime"  # legacy Full layout
PAYLOAD_MODELS = INSTALLER_ROOT / "models"  # legacy/unpacked model layout
OFFLINE_ASSET_ARCHIVE = INSTALLER_ROOT / "runtime-package" / "memo-offline-assets.zip"
OFFLINE_ASSET_MANIFEST = INSTALLER_ROOT / "runtime-package" / "memo-offline-assets.manifest.json"
DEFAULT_RUNTIME_PYTHON = PAYLOAD_RUNTIME / "python.exe"
MANAGED_FORBIDDEN_PARTS = {"data", "logs", "backups", ".venv", "node_modules", "release", "install_output", "reports", "__pycache__"}
MANAGED_FORBIDDEN_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".log", ".pyc", ".pem", ".key"}
MANAGED_DIRECTORIES = ("memo", "scripts", "dashboard/dist")
MANAGED_TOP_LEVEL = {"start_all.bat", "stop_all.bat", "requirements.txt", "pyproject.toml", ".env.example", "mcp_config.example.json", "README.md"}


def managed_app_files(app_root: Path) -> dict[str, str]:
    """Return the immutable program baseline without user data or caches."""
    fingerprints = {}
    if not app_root.is_dir():
        return fingerprints
    for path in sorted((item for item in app_root.rglob("*") if item.is_file()), key=lambda item: item.as_posix()):
        relative = path.relative_to(app_root)
        relative_name = relative.as_posix()
        if relative_name not in MANAGED_TOP_LEVEL and not any(relative_name.startswith(f"{root}/") for root in MANAGED_DIRECTORIES):
            continue
        lowered = {part.lower() for part in relative.parts}
        if lowered & MANAGED_FORBIDDEN_PARTS:
            continue
        if path.name == "memo-install-manifest.json":
            continue
        if path.name.startswith(".env") and path.name != ".env.example":
            continue
        if path.suffix.lower() in MANAGED_FORBIDDEN_SUFFIXES:
            continue
        fingerprints[relative.as_posix()] = sha256_file(path)
    return fingerprints


def copy_tree(source: Path, target: Path, multithreaded: bool = False) -> None:
    if not source.is_dir():
        raise RuntimeError(f"installer payload missing: {source}")
    target.mkdir(parents=True, exist_ok=True)
    if multithreaded and os.name == "nt":
        command = [
            "robocopy",
            str(source),
            str(target),
            "/E",
            "/MT:16",
            "/R:1",
            "/W:1",
            "/NFL",
            "/NDL",
            "/NJH",
            "/NJS",
            "/NP",
        ]
        run = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20 * 60)
        if run.returncode > 7:
            raise RuntimeError(f"Runtime copy failed with robocopy exit {run.returncode}: {run.stderr or run.stdout}")
        return
    for entry in source.iterdir():
        destination = target / entry.name
        if entry.is_dir():
            shutil.copytree(entry, destination, dirs_exist_ok=True)
        else:
            shutil.copy2(entry, destination)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def offline_assets_available() -> bool:
    return OFFLINE_ASSET_ARCHIVE.is_file() and OFFLINE_ASSET_MANIFEST.is_file()


def offline_assets_needed(paths) -> dict:
    if not offline_assets_available():
        return {"available": False, "runtime": False, "model": False, "manifest": {}}
    manifest = read_json(OFFLINE_ASSET_MANIFEST)
    runtime_manifest = read_json(paths.runtime_root / ".memo-runtime-manifest.json")
    model_manifest = read_json(paths.embedding_model_root / "model-manifest.json")
    return {
        "available": True,
        "runtime": runtime_manifest.get("fingerprint") != manifest.get("runtimeFingerprint"),
        "model": model_manifest.get("fingerprint") != manifest.get("modelFingerprint"),
        "manifest": manifest,
    }


def extract_offline_assets(archive: Path, staging: Path, prefixes: set[str]) -> None:
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            pure = PurePosixPath(info.filename)
            if pure.is_absolute() or ".." in pure.parts:
                raise RuntimeError(f"Unsafe path in offline asset archive: {info.filename}")
            if not pure.parts or pure.parts[0] not in prefixes:
                continue
            destination = staging.joinpath(*pure.parts)
            if info.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(info, "r") as source, destination.open("wb") as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)


def swap_program_directory(source: Path, target: Path, release_locks=None, retries: int = 1) -> dict:
    """Atomically replace a program directory with bounded Windows lock retries.

    Full extraction can take several minutes. During that window an external MCP
    client may respawn the old Memo runtime after the installer's initial stop.
    release_locks is therefore called immediately before every rename attempt.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    previous = target.with_name(f"{target.name}.previous-{uuid.uuid4().hex}")
    if target.exists():
        last_error = None
        for attempt in range(max(1, retries)):
            if release_locks:
                release_locks()
            try:
                target.replace(previous)
                last_error = None
                break
            except PermissionError as exc:
                last_error = exc
                if attempt + 1 < max(1, retries):
                    time.sleep(min(0.35 * (attempt + 1), 1.5))
        if last_error:
            raise RuntimeError(
                f"Runtime目录仍被其他程序占用，已自动重试{max(1, retries)}次。"
                "请完全退出正在使用Memo MCP的Hana、Codex或其他Agent后重试安装。"
                f"原始错误：{last_error}"
            ) from last_error
    try:
        source.replace(target)
    except Exception:
        if previous.exists() and not target.exists():
            previous.replace(target)
        raise
    return {"target": target, "previous": previous if previous.exists() else None}


def install_offline_assets(paths) -> dict:
    needed = offline_assets_needed(paths)
    if not needed["available"] or not (needed["runtime"] or needed["model"]):
        return {"runtimeCopied": False, "modelCopied": False, "_swaps": [], "_staging": None}
    published_hash = str(needed["manifest"].get("sha256") or "").lower()
    if not published_hash or sha256_file(OFFLINE_ASSET_ARCHIVE) != published_hash:
        raise RuntimeError("Full offline asset archive SHA-256 verification failed")
    staging = paths.runtime_root.parent / f".offline-assets-{uuid.uuid4().hex}"
    prefixes = set()
    if needed["runtime"]:
        prefixes.add("runtime")
    if needed["model"]:
        prefixes.add("models")
    extract_offline_assets(OFFLINE_ASSET_ARCHIVE, staging, prefixes)
    swaps = []
    try:
        if needed["runtime"]:
            source_runtime = staging / "runtime"
            if not (source_runtime / "python.exe").is_file():
                raise RuntimeError("Offline asset archive does not contain a complete runtime")
            # Extraction may take minutes, during which an Agent can respawn its
            # Memo MCP process. Stop it again immediately before the atomic swap.
            swaps.append(
                swap_program_directory(
                    source_runtime,
                    paths.runtime_root,
                    release_locks=lambda: stop_runtime_processes(paths.runtime_root),
                    retries=8,
                )
            )
        if needed["model"]:
            source_model = staging / "models" / "bge-small-zh-v1.5"
            if not (source_model / "model-manifest.json").is_file():
                raise RuntimeError("Offline asset archive does not contain the pinned BGE model")
            swaps.append(swap_program_directory(source_model, paths.embedding_model_root))
    except Exception:
        rollback_offline_assets({"_swaps": swaps, "_staging": staging})
        raise
    return {
        "runtimeCopied": needed["runtime"],
        "modelCopied": needed["model"],
        "runtimeFingerprint": needed["manifest"].get("runtimeFingerprint", ""),
        "modelFingerprint": needed["manifest"].get("modelFingerprint", ""),
        "_swaps": swaps,
        "_staging": staging,
    }


def rollback_offline_assets(result: dict) -> None:
    for swap in reversed(result.get("_swaps") or []):
        target = swap["target"]
        previous = swap.get("previous")
        failed = target.with_name(f"{target.name}.failed-{uuid.uuid4().hex}")
        if target.exists():
            target.replace(failed)
        if previous and previous.exists():
            previous.replace(target)
        if failed.exists():
            shutil.rmtree(failed, ignore_errors=True)
    staging = result.get("_staging")
    if staging and Path(staging).exists():
        shutil.rmtree(staging, ignore_errors=True)


def finalize_offline_assets(result: dict) -> None:
    for swap in result.get("_swaps") or []:
        previous = swap.get("previous")
        if previous and previous.exists():
            shutil.rmtree(previous, ignore_errors=True)
    staging = result.get("_staging")
    if staging and Path(staging).exists():
        shutil.rmtree(staging, ignore_errors=True)


def public_offline_result(result: dict) -> dict:
    return {key: value for key, value in result.items() if not key.startswith("_")}


def migrate_legacy_user_state(source_root: str, target_paths) -> dict:
    """Copy an existing development/legacy Memo state into the formal root.

    The source is never modified. Migration is refused when the formal target
    already contains a database, because installation must never guess how to
    merge two independent memory stores.
    """
    if not source_root.strip():
        return {}
    source = install_paths({"MEMO_USER_ROOT": source_root.strip()})
    if not source.database.exists():
        raise RuntimeError(f"旧数据目录中未找到数据库：{source.database}")
    if target_paths.database.exists():
        raise RuntimeError("正式数据目录已经存在数据库，不能自动覆盖或合并。请在向导中选择要继续使用的数据。")

    # Stop any process recorded by the source data root before copying SQLite
    # and its WAL/SHM sidecars. The source files themselves remain untouched.
    source_stop = stop_existing_services(source)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    migration_backup = target_paths.backups_root / f"legacy-before-migration-{stamp}"
    migration_backup.mkdir(parents=True, exist_ok=False)
    target_paths.data_root.mkdir(parents=True, exist_ok=True)
    copied = []
    for suffix in ("", "-wal", "-shm"):
        source_file = Path(f"{source.database}{suffix}")
        if not source_file.exists():
            continue
        backup_file = migration_backup / source_file.name
        target_file = Path(f"{target_paths.database}{suffix}")
        shutil.copy2(source_file, backup_file)
        shutil.copy2(source_file, target_file)
        if source_file.stat().st_size != target_file.stat().st_size:
            raise RuntimeError(f"迁移复制校验失败：{source_file.name}")
        copied.append(str(target_file))

    source_env = source.env_file if source.env_file.exists() else source.user_root / ".env"
    if source_env.exists() and not target_paths.env_file.exists():
        target_paths.config_root.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_env, migration_backup / "source.env")
        shutil.copy2(source_env, target_paths.env_file)
    return {"source": str(source.user_root), "target": str(target_paths.user_root), "backup": str(migration_backup), "files": copied, "sourceStopped": source_stop}


def backup_user_state(paths) -> dict:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    paths.backups_root.mkdir(parents=True, exist_ok=True)
    result = {}
    if paths.database.exists():
        target = paths.backups_root / f"memo-before-installer-upgrade-{stamp}.db"
        shutil.copy2(paths.database, target)
        result["database"] = str(target)
    if paths.env_file.exists():
        target = paths.backups_root / f"env-before-installer-upgrade-{stamp}.env"
        shutil.copy2(paths.env_file, target)
        result["env"] = str(target)
    return result


def write_manifest(paths) -> None:
    paths.app_root.mkdir(parents=True, exist_ok=True)
    paths.manifest.write_text(
        json.dumps(
            {
                "schemaVersion": 2,
                "serviceVersion": SERVICE_VERSION,
                "installedAt": datetime.now().isoformat(timespec="seconds"),
                "installedFiles": managed_app_files(paths.app_root),
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )


def read_existing_api_key(paths) -> bool:
    return bool(read_env(paths.env_file).get("LLM_API_KEY"))


def stop_runtime_processes(runtime_root: Path) -> list[str]:
    """Stop other Python processes executing from the target runtime.

    MCP clients are external to Memo's PID files and can keep native .pyd files
    locked during a Full upgrade. PowerShell is bounded and the current
    installer runner PID is explicitly excluded.
    """
    if not (runtime_root / "python.exe").exists():
        return []
    root = str(runtime_root.resolve())
    quoted_root = root.replace("'", "''")
    script = f"""
$root = [IO.Path]::GetFullPath('{quoted_root}')
$exclude = {os.getpid()}
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
  Where-Object {{ $_.ProcessId -ne $exclude -and $_.ExecutablePath -and [IO.Path]::GetFullPath($_.ExecutablePath).StartsWith($root, [StringComparison]::OrdinalIgnoreCase) }} |
  ForEach-Object {{
    $pidToStop = $_.ProcessId
    Write-Output $pidToStop
    Stop-Process -Id $pidToStop -Force -ErrorAction SilentlyContinue
    Wait-Process -Id $pidToStop -Timeout 3 -ErrorAction SilentlyContinue
  }}
"""
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    try:
        run = subprocess.run(["powershell.exe", "-NoProfile", "-EncodedCommand", encoded], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=25)
        return [line.strip() for line in run.stdout.splitlines() if line.strip().isdigit()]
    except Exception:
        return []


def stop_existing_services(paths) -> dict:
    """Best-effort stop before overwriting app and runtime files."""
    result = {"stopScript": "missing", "killedPids": [], "runtimePids": []}
    env = {**os.environ, **service_environment(paths)}
    stop_script = paths.app_root / "stop_all.bat"
    if stop_script.exists():
        run = subprocess.run(["cmd.exe", "/c", str(stop_script)], cwd=paths.app_root, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        result["stopScript"] = "ok" if run.returncode == 0 else f"exit:{run.returncode}"
    pid_dir = paths.data_root / "pids"
    if pid_dir.exists():
        for pid_file in pid_dir.glob("*.pid"):
            try:
                pid = pid_file.read_text(encoding="ascii", errors="ignore").strip()
                if pid and pid.isdigit():
                    subprocess.run(["taskkill", "/PID", pid, "/F", "/T"], capture_output=True, text=True, timeout=15)
                    result["killedPids"].append(pid)
            except Exception:
                pass
    result["runtimePids"] = stop_runtime_processes(paths.runtime_root)
    return result


def configure_embedded_runtime_path(paths) -> None:
    python = runtime_python_path(paths)
    runtime_root = python.parent
    pth_files = list(runtime_root.glob("python*._pth"))
    if not pth_files:
        return
    pth = pth_files[0]
    app_line = str(paths.app_root)
    lines = pth.read_text(encoding="utf-8", errors="replace").splitlines()
    if app_line not in lines:
        # Keep the app root before import site so embedded Python can import memo
        # regardless of the working directory used by service scripts.
        insert_at = next((i for i, line in enumerate(lines) if line.strip() == "import site"), len(lines))
        lines.insert(insert_at, app_line)
        pth.write_text("\n".join(lines) + "\n", encoding="utf-8")


def initialize_service(paths) -> None:
    python = runtime_python_path(paths)
    if not python.exists():
        raise RuntimeError(f"内置 Python Runtime 不完整，无法初始化 Memo 服务：{python}")
    configure_embedded_runtime_path(paths)
    env = {**service_environment(paths), "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    run = subprocess.run(
        [str(python), "-c", "from memo.core.engine import engine; engine.init(); print('Memo database initialized')"],
        cwd=paths.app_root,
        env={**__import__("os").environ, **env},
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    if run.returncode != 0:
        raise RuntimeError(f"数据库初始化失败：{run.stderr or run.stdout}")


def install(api_key: str = "", base_url: str = "", model: str = "", migrate_from: str = "") -> dict:
    paths = install_paths()
    state = detect_state(paths)
    ensure_user_dirs(paths)
    migration = migrate_legacy_user_state(migrate_from, paths) if migrate_from.strip() else {}
    if migration:
        state = detect_state(paths)
    stable_runtime_present = (paths.runtime_root / "python.exe").exists()
    asset_plan = offline_assets_needed(paths)
    assets_current = not asset_plan["available"] or not (asset_plan["runtime"] or asset_plan["model"])
    if (
        state["mode"] == "healthy_latest"
        and stable_runtime_present
        and assets_current
        and not any(value.strip() for value in (api_key, base_url, model))
    ):
        return {
            "ok": True,
            "skipped": True,
            "reason": "already_latest",
            "before": state,
            "after": state,
            "backups": {},
            "runtime": {"copied": False, "path": str(paths.runtime_root)},
            "model": {"copied": False, "path": str(paths.embedding_model_root)},
            "config": {"envFile": str(paths.env_file), "hasApiKey": bool(read_existing_api_key(paths))},
        }
    active_runtime_root = runtime_python_path(paths).parent
    if (
        not DEFAULT_RUNTIME_PYTHON.exists()
        and not offline_assets_available()
        and (active_runtime_root / "python.exe").exists()
        and active_runtime_root.resolve() != paths.runtime_root.resolve()
        and not migrate_from.strip()
    ):
        raise RuntimeError(
            f"Lite 检测到可用 Runtime 位于 {active_runtime_root}，但当前目标 {paths.user_root} 没有已确认的数据。"
            "请返回上一步选择已有 Memo 数据目录；如需创建全新环境，请使用 Full 版。"
        )
    should_stop = state["mode"] in {"healthy_latest", "upgrade", "repair"} or stable_runtime_present
    stop_result = stop_existing_services(paths) if should_stop else {"stopScript": "not_needed", "killedPids": []}
    backups = backup_user_state(paths) if state["mode"] in {"upgrade", "repair"} else {}
    offline_result = {"runtimeCopied": False, "modelCopied": False, "_swaps": [], "_staging": None}
    runtime_copied = False
    model_copied = False
    try:
        copy_tree(PAYLOAD_APP, paths.app_root)
        if offline_assets_available():
            offline_result = install_offline_assets(paths)
            runtime_copied = bool(offline_result.get("runtimeCopied"))
            model_copied = bool(offline_result.get("modelCopied"))
        elif DEFAULT_RUNTIME_PYTHON.exists():
            payload_manifest = read_json(PAYLOAD_RUNTIME / ".memo-runtime-manifest.json")
            installed_manifest = read_json(paths.runtime_root / ".memo-runtime-manifest.json")
            if not payload_manifest or payload_manifest.get("fingerprint") != installed_manifest.get("fingerprint"):
                copy_tree(PAYLOAD_RUNTIME, paths.runtime_root, multithreaded=True)
                runtime_copied = True
            source_model = PAYLOAD_MODELS / "bge-small-zh-v1.5"
            if (source_model / "model-manifest.json").exists():
                source_manifest = read_json(source_model / "model-manifest.json")
                target_manifest = read_json(paths.embedding_model_root / "model-manifest.json")
                if source_manifest.get("fingerprint") != target_manifest.get("fingerprint"):
                    copy_tree(source_model, paths.embedding_model_root, multithreaded=True)
                    model_copied = True
        elif (active_runtime_root / "python.exe").exists() and active_runtime_root.resolve() != paths.runtime_root.resolve():
            # Lite may carry the stable runtime only as part of an explicit
            # user-root migration. Never create a second runtime implicitly.
            copy_tree(active_runtime_root, paths.runtime_root, multithreaded=True)
            runtime_copied = True
        if not (paths.runtime_root / "python.exe").exists():
            raise RuntimeError("安装后未找到稳定 Runtime，请使用 Full 版修复。")
        os.environ["MEMO_RUNTIME_ROOT"] = str(paths.runtime_root)
        configure_embedded_runtime_path(paths)
        config = write_user_config(paths, api_key=api_key, base_url=base_url, model=model)
        initialize_service(paths)
        write_manifest(paths)
        finalize_offline_assets(offline_result)
    except Exception:
        rollback_offline_assets(offline_result)
        raise
    return {
        "ok": True,
        "skipped": False,
        "before": state,
        "after": detect_state(paths),
        "backups": backups,
        "migration": migration,
        "runtime": {"copied": runtime_copied, "path": str(paths.runtime_root)},
        "model": {"copied": model_copied, "path": str(paths.embedding_model_root)},
        "offlineAssets": public_offline_result(offline_result),
        "config": config,
        "stopped": stop_result,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--detect", action="store_true")
    parser.add_argument("--user-root", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--migrate-from", default="")
    args = parser.parse_args()
    if args.user_root.strip():
        __import__("os").environ["MEMO_USER_ROOT"] = args.user_root.strip()
    if DEFAULT_RUNTIME_PYTHON.exists() and not offline_assets_available() and not os.environ.get("MEMO_RUNTIME_ROOT"):
        os.environ["MEMO_RUNTIME_ROOT"] = str(PAYLOAD_RUNTIME)
    try:
        if args.detect:
            # Detection must be read-only. Creating empty data/config folders at
            # a guessed root makes later runs mistake that location for a real
            # installation and is especially harmful across Windows user scopes.
            paths = install_paths()
            print(json.dumps(detect_state(paths), ensure_ascii=False, indent=2))
        else:
            print(json.dumps(install(args.api_key, args.base_url, args.model, args.migrate_from), ensure_ascii=False, indent=2))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
