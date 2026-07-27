"""Switch Memo production config to a clean source-aware database.

Default is dry-run. Apply requires:

    python scripts/switch_to_clean_source_aware_db.py --apply --confirm CLEAN_SOURCE_AWARE_RESET

Safety model:
- does not delete data/memo.db
- does not delete or move WAL/SHM files
- creates a fresh data/memo_source_aware.db from migrations
- backs up current DB and .env before editing .env
- updates/sets MEMO_DB_PATH in .env to the clean DB
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
BACKUP_DIR = DATA_DIR / "backups"
MIGRATIONS_DIR = PROJECT_ROOT / "memo" / "store" / "migrations"
ENV_PATH = PROJECT_ROOT / ".env"
CONFIRM_TOKEN = "CLEAN_SOURCE_AWARE_RESET"
TARGET_DB = DATA_DIR / "memo_source_aware.db"

REQUIRED_SCHEMA = {
    "source_sessions": {"agent_session_id", "source_hash", "original_title", "title_source", "display_title", "display_title_source"},
    "source_turns": {"source_session_id", "content", "content_hash", "metadata_json", "turn_index"},
    "episodes": {"source_session_id", "start_turn_id", "end_turn_id"},
    "episode_turns": {"episode_id", "turn_id", "role_in_episode"},
    "memory_turn_sources": {"memory_id", "turn_id", "evidence_role"},
    "memory_units": {"source_session_id", "episode_id", "source_turn_start_id", "source_turn_end_id", "memory_granularity", "speaker_scope", "source_confidence", "is_canonical"},
}


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_env_db_path() -> Path:
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip().startswith("MEMO_DB_PATH="):
                raw = line.split("=", 1)[1].strip().strip('"').strip("'")
                p = Path(raw)
                return p if p.is_absolute() else PROJECT_ROOT / p
    return DATA_DIR / "memo.db"


def apply_migrations(db_path: Path) -> int:
    if db_path.exists():
        raise FileExistsError(f"target already exists: {db_path}")
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)")
    latest = 0
    for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
        version = int(migration.stem.split("_", 1)[0])
        latest = max(latest, version)
        conn.executescript(migration.read_text(encoding="utf-8"))
        conn.execute("INSERT OR IGNORE INTO schema_version(version) VALUES (?)", (version,))
    conn.commit()
    conn.close()
    return latest


def validate_schema(db_path: Path) -> dict:
    conn = sqlite3.connect(db_path)
    version_row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    version = int(version_row[0] or 0)
    missing: dict[str, list[str]] = {}
    for table, required_cols in REQUIRED_SCHEMA.items():
        found = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if not found:
            missing[table] = ["<table>"]
            continue
        absent = sorted(required_cols - found)
        if absent:
            missing[table] = absent
    counts = {
        "sessions": conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0],
        "memory_units": conn.execute("SELECT COUNT(*) FROM memory_units").fetchone()[0],
        "source_sessions": conn.execute("SELECT COUNT(*) FROM source_sessions").fetchone()[0],
    }
    conn.close()
    return {"schema_version": version, "ready": not missing, "missing": missing, "counts": counts}


def backup_current(current_db: Path, stamp: str) -> dict:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    result: dict = {"timestamp": stamp, "current_db": str(current_db), "backups": {}}
    if current_db.exists():
        # Safe checkpoint only. Do not delete/move WAL/SHM.
        try:
            conn = sqlite3.connect(current_db)
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.close()
            result["checkpoint"] = "ok"
        except Exception as exc:
            result["checkpoint"] = f"failed: {type(exc).__name__}: {exc}"
        db_backup = BACKUP_DIR / f"memo-before-clean-source-aware-{stamp}.db"
        shutil.copy2(current_db, db_backup)
        result["backups"]["db"] = {"path": str(db_backup), "size": db_backup.stat().st_size, "sha256": sha256(db_backup)}
    if ENV_PATH.exists():
        env_backup = BACKUP_DIR / f"env-before-clean-source-aware-{stamp}.txt"
        shutil.copy2(ENV_PATH, env_backup)
        result["backups"]["env"] = {"path": str(env_backup), "size": env_backup.stat().st_size, "sha256": sha256(env_backup)}
    return result


def update_env_db_path(target: Path) -> None:
    rel = target.relative_to(PROJECT_ROOT).as_posix()
    line = f"MEMO_DB_PATH={rel}"
    lines = []
    replaced = False
    if ENV_PATH.exists():
        lines = ENV_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    for i, old in enumerate(lines):
        if old.strip().startswith("MEMO_DB_PATH="):
            lines[i] = line
            replaced = True
            break
    if not replaced:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(line)
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--target-db", default=str(TARGET_DB))
    args = parser.parse_args()

    stamp = now_stamp()
    target = Path(args.target_db)
    if not target.is_absolute():
        target = PROJECT_ROOT / target
    current_db = read_env_db_path()
    building = target.with_name(target.stem + f".building-{stamp}" + target.suffix)

    plan = {
        "dry_run": not args.apply,
        "current_db": str(current_db),
        "target_db": str(target),
        "building_db": str(building),
        "env_path": str(ENV_PATH),
        "will_delete_old_db": False,
        "will_delete_or_move_wal_shm": False,
        "will_update_env": bool(args.apply),
    }

    if not args.apply:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    if args.confirm != CONFIRM_TOKEN:
        raise SystemExit(f"真实切换必须传 --confirm {CONFIRM_TOKEN}")
    if target.exists():
        raise SystemExit(f"目标新库已存在，拒绝覆盖：{target}")

    backup = backup_current(current_db, stamp)
    latest = apply_migrations(building)
    validation = validate_schema(building)
    if not validation["ready"]:
        raise SystemExit(f"新库 schema 验证失败：{json.dumps(validation, ensure_ascii=False)}")
    building.replace(target)
    update_env_db_path(target)

    manifest = {
        **plan,
        "dry_run": False,
        "latest_migration": latest,
        "validation": validation,
        "backup": backup,
        "target": {"path": str(target), "size": target.stat().st_size, "sha256": sha256(target)},
    }
    manifest_path = BACKUP_DIR / f"clean-source-aware-switch-{stamp}.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "manifest": str(manifest_path), "target_db": str(target), "validation": validation}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
