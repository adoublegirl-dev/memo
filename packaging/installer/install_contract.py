"""Memo full-installer contract: paths, state detection, and safe user config writes.

This module deliberately has no dependency on the developer's Memo data. It only
operates on the target user's LocalAppData directory at install time.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

PRODUCT = "Memo"
SERVICE_VERSION = "0.10.8-alpha.4"


def normalize_user_root(path: str | Path) -> Path:
    """Return the Memo root directory.

    Users may choose either the Memo root containing data/memo_source_aware.db,
    or the data directory itself. Normalize both to the root.
    """
    root = Path(path).expanduser()
    if root.name.lower() == "data" and (root / "memo_source_aware.db").exists():
        return root.parent
    if (root / "memo_source_aware.db").exists():
        return root.parent
    return root


def local_app_data(env: dict[str, str] | None = None) -> Path:
    source = env or os.environ
    explicit_root = source.get("MEMO_USER_ROOT")
    if explicit_root:
        return normalize_user_root(explicit_root)
    base = source.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / PRODUCT


@dataclass(frozen=True)
class InstallPaths:
    user_root: Path

    @property
    def app_root(self) -> Path:
        return self.user_root / "Programs" / PRODUCT / "app"

    @property
    def runtime_root(self) -> Path:
        return self.user_root / "Programs" / PRODUCT / "runtime"

    @property
    def models_root(self) -> Path:
        return self.user_root / "Programs" / PRODUCT / "models"

    @property
    def embedding_model_root(self) -> Path:
        return self.models_root / "bge-small-zh-v1.5"

    @property
    def config_root(self) -> Path:
        return self.user_root / "config"

    @property
    def env_file(self) -> Path:
        return self.config_root / ".env"

    @property
    def data_root(self) -> Path:
        return self.user_root / "data"

    @property
    def database(self) -> Path:
        return self.data_root / "memo_source_aware.db"

    @property
    def logs_root(self) -> Path:
        return self.data_root / "logs"

    @property
    def backups_root(self) -> Path:
        return self.data_root / "backups"

    @property
    def manifest(self) -> Path:
        return self.app_root / "memo-install-manifest.json"


def install_paths(env: dict[str, str] | None = None) -> InstallPaths:
    return InstallPaths(local_app_data(env))


def read_manifest(paths: InstallPaths) -> dict:
    try:
        return json.loads(paths.manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def runtime_python_path(paths: InstallPaths) -> Path:
    runtime_root = os.environ.get("MEMO_RUNTIME_ROOT", "").strip()
    if runtime_root:
        return Path(runtime_root) / "python.exe"
    return paths.runtime_root / "python.exe"


def detect_state(paths: InstallPaths, target_version: str = SERVICE_VERSION) -> dict:
    manifest = read_manifest(paths)
    app_present = (paths.app_root / "start_all.bat").exists() and (paths.app_root / "memo").is_dir()
    runtime_present = runtime_python_path(paths).exists()
    model_present = (paths.embedding_model_root / "model-manifest.json").exists()
    data_present = paths.database.exists()
    current = str(manifest.get("serviceVersion") or "")
    if app_present and runtime_present and current == target_version:
        mode = "healthy_latest"
    elif app_present or data_present:
        mode = "upgrade" if app_present else "repair"
    else:
        mode = "fresh"
    return {
        "mode": mode,
        "appPresent": app_present,
        "runtimePresent": runtime_present,
        "modelPresent": model_present,
        "dataPresent": data_present,
        "currentServiceVersion": current,
        "targetServiceVersion": target_version,
        "paths": {**{key: str(getattr(paths, key)) for key in ("user_root", "app_root", "runtime_root", "models_root", "embedding_model_root", "env_file", "database", "logs_root", "backups_root")}, "runtime_python": str(runtime_python_path(paths))},
    }


def ensure_user_dirs(paths: InstallPaths) -> None:
    for folder in (paths.config_root, paths.data_root, paths.logs_root, paths.backups_root):
        folder.mkdir(parents=True, exist_ok=True)


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def write_user_config(paths: InstallPaths, api_key: str = "", base_url: str = "", model: str = "") -> dict:
    """Merge only installer-owned fields; preserve existing user values by default."""
    ensure_user_dirs(paths)
    values = read_env(paths.env_file)
    values["MEMO_USER_ROOT"] = str(paths.user_root)
    values["MEMO_DATA_ROOT"] = str(paths.data_root)
    values["MEMO_DB_PATH"] = str(paths.database)
    if (paths.embedding_model_root / "model-manifest.json").exists():
        values["MEMO_EMBEDDING_MODEL"] = str(paths.embedding_model_root)
    if api_key.strip():
        values["LLM_API_KEY"] = api_key.strip()
    if base_url.strip():
        values["LLM_BASE_URL"] = base_url.strip()
    if model.strip():
        values["MEMO_EXTRACTION_MODEL"] = model.strip()
        values["MEMO_GATING_MODEL"] = model.strip()
    ordered = ["MEMO_USER_ROOT", "MEMO_DATA_ROOT", "MEMO_DB_PATH", "MEMO_EMBEDDING_MODEL", "LLM_API_KEY", "LLM_BASE_URL", "MEMO_EXTRACTION_MODEL", "MEMO_GATING_MODEL"]
    lines = [f"{key}={values[key]}" for key in ordered if values.get(key, "")]
    lines.extend(f"{key}={value}" for key, value in values.items() if key not in ordered)
    paths.env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"envFile": str(paths.env_file), "hasApiKey": bool(values.get("LLM_API_KEY")), "database": str(paths.database)}


def service_environment(paths: InstallPaths) -> dict[str, str]:
    runtime_python = runtime_python_path(paths)
    environment = {
        "MEMO_USER_ROOT": str(paths.user_root),
        "MEMO_DATA_ROOT": str(paths.data_root),
        "MEMO_DB_PATH": str(paths.database),
        "MEMO_ENV_FILE": str(paths.env_file),
        "MEMO_LOG_DIR": str(paths.logs_root),
        "MEMO_PID_DIR": str(paths.data_root / "pids"),
        "PYTHON_EXE": str(runtime_python),
        "MEMO_RUNTIME_ROOT": str(runtime_python.parent),
    }
    if (paths.embedding_model_root / "model-manifest.json").exists():
        environment["MEMO_EMBEDDING_MODEL"] = str(paths.embedding_model_root)
    return environment
