"""Prepare the single production database for Memo service updates.

Rules:
- data/memo_source_aware.db is the only runtime database.
- legacy data/memo.db is backup-only and is never selected as runtime DB.
- an existing source-aware DB is never overwritten or recreated.
- when a source-aware DB is absent, create an empty validated one from migrations.

Default is dry-run. Real execution requires:
    python scripts/prepare_source_aware_runtime.py --apply --confirm PREPARE_SOURCE_AWARE
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path

try:  # 兼容 `python scripts/...py` 直接执行与 pytest 模块导入两种路径。
    from switch_to_clean_source_aware_db import apply_migrations, validate_schema
except ModuleNotFoundError:
    from scripts.switch_to_clean_source_aware_db import apply_migrations, validate_schema

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
BACKUP_DIR = DATA_DIR / "backups"
ENV_PATH = PROJECT_ROOT / ".env"
TARGET_DB = DATA_DIR / "memo_source_aware.db"
LEGACY_DB = DATA_DIR / "memo.db"
CONFIRM_TOKEN = "PREPARE_SOURCE_AWARE"


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_env_db_path(env_path: Path = ENV_PATH, project_root: Path = PROJECT_ROOT) -> Path | None:
    if not env_path.exists():
        return None
    for raw_line in env_path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() != "MEMO_DB_PATH":
            continue
        value = value.strip().strip("\"'")
        if not value:
            return None
        resolved = Path(value)
        return resolved if resolved.is_absolute() else project_root / resolved
    return None


def update_env_to_target(env_path: Path = ENV_PATH, target_db: Path = TARGET_DB, project_root: Path = PROJECT_ROOT) -> None:
    try:
        configured = target_db.relative_to(project_root).as_posix()
    except ValueError:
        configured = str(target_db)
    new_line = f"MEMO_DB_PATH={configured}"
    lines = env_path.read_text(encoding="utf-8-sig", errors="replace").splitlines() if env_path.exists() else []
    for index, old in enumerate(lines):
        if old.strip().startswith("MEMO_DB_PATH="):
            lines[index] = new_line
            break
    else:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(new_line)
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def backup_file(path: Path, backup_dir: Path, stamp: str, label: str) -> dict | None:
    if not path.exists():
        return None
    backup_dir.mkdir(parents=True, exist_ok=True)
    destination = backup_dir / f"{label}-{stamp}{path.suffix}"
    shutil.copy2(path, destination)
    return {"source": str(path), "backup": str(destination), "size": destination.stat().st_size, "sha256": sha256(destination)}


def build_plan(
    project_root: Path = PROJECT_ROOT,
    env_path: Path = ENV_PATH,
    target_db: Path = TARGET_DB,
    legacy_db: Path = LEGACY_DB,
) -> dict:
    configured = read_env_db_path(env_path, project_root)
    target_exists = target_db.exists()
    configured_is_target = configured is not None and configured.resolve() == target_db.resolve()
    legacy_configured = configured is not None and configured.resolve() != target_db.resolve()
    return {
        "runtime_db": str(target_db),
        "target_exists": target_exists,
        "configured_db": str(configured) if configured else None,
        "configured_is_target": configured_is_target,
        "legacy_configured": legacy_configured,
        "legacy_db_exists": legacy_db.exists(),
        "action": "preserve_existing_source_aware" if target_exists else "create_new_source_aware",
        "will_overwrite_target": False,
        "will_delete_or_move_legacy": False,
        "will_update_env": not configured_is_target,
    }


def apply_prepare(plan: dict, project_root: Path = PROJECT_ROOT, env_path: Path = ENV_PATH, target_db: Path = TARGET_DB, backup_dir: Path = BACKUP_DIR) -> dict:
    stamp = now_stamp()
    backups: dict[str, dict] = {}
    configured = Path(plan["configured_db"]) if plan["configured_db"] else None

    # Backup the currently configured old DB (if any) before changing its pointer.
    if configured and configured.resolve() != target_db.resolve():
        copied = backup_file(configured, backup_dir, stamp, "memo-legacy-before-source-aware")
        if copied:
            backups["legacy_db"] = copied
    # A legacy db may exist without an env pointer; still preserve it once before first switch.
    elif not target_db.exists():
        legacy = project_root / "data" / "memo.db"
        copied = backup_file(legacy, backup_dir, stamp, "memo-legacy-before-source-aware")
        if copied:
            backups["legacy_db"] = copied

    if env_path.exists():
        copied_env = backup_file(env_path, backup_dir, stamp, "env-before-source-aware")
        if copied_env:
            backups["env"] = copied_env

    created = False
    validation = None
    if not target_db.exists():
        target_db.parent.mkdir(parents=True, exist_ok=True)
        building = target_db.with_name(f"{target_db.stem}.building-{stamp}{target_db.suffix}")
        try:
            latest = apply_migrations(building)
            validation = validate_schema(building)
            if not validation["ready"]:
                raise RuntimeError(f"新库 schema 校验失败: {json.dumps(validation, ensure_ascii=False)}")
            building.replace(target_db)
            created = True
        finally:
            if building.exists():
                building.unlink()
    else:
        validation = validate_schema(target_db)
        if not validation["ready"]:
            raise RuntimeError(f"现有 source-aware 库 schema 校验失败，拒绝覆盖: {json.dumps(validation, ensure_ascii=False)}")
        latest = validation["schema_version"]

    update_env_to_target(env_path, target_db, project_root)
    result = {
        "ok": True,
        "runtime_db": str(target_db),
        "created_new_source_aware_db": created,
        "preserved_existing_source_aware_db": not created,
        "latest_migration": latest,
        "validation": validation,
        "backups": backups,
        "old_memo_db_is_runtime": False,
    }
    backup_dir.mkdir(parents=True, exist_ok=True)
    manifest = backup_dir / f"prepare-source-aware-{stamp}.json"
    manifest.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    result["manifest"] = str(manifest)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    plan = build_plan()
    if not args.apply:
        print(json.dumps({"ok": True, "dry_run": True, **plan}, ensure_ascii=False))
        return 0
    if args.confirm != CONFIRM_TOKEN:
        print(json.dumps({"ok": False, "message": f"真实执行必须传 --confirm {CONFIRM_TOKEN}"}, ensure_ascii=False))
        return 2
    try:
        print(json.dumps(apply_prepare(plan), ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"ok": False, "message": str(exc)}, ensure_ascii=False))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
