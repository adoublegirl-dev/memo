"""归档当前 Memo 数据库与 .env 的安全工具。

Phase D 工具，默认 dry-run，不修改任何文件。真实执行必须显式传入：

    python scripts/archive_current_db.py --apply --confirm ARCHIVE

安全原则：
- 不删除、不移动原数据库、WAL、SHM 或 .env。
- 默认只做 dry-run。
- 真实归档只复制 memo.db 和 .env（如果存在）到 backups 子目录。
- 检测到 .db-wal / .db-shm 时只提示风险，不复制、不删除。
- 输出文件大小、SHA256、原路径、新路径，便于审计。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BACKUP_DIR = PROJECT_ROOT / "data" / "backups"
CONFIRM_WORD = "ARCHIVE"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def iso_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def file_info(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False}
    st = path.stat()
    return {
        "path": str(path),
        "exists": True,
        "size": st.st_size,
        "mtime": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
        "sha256": sha256_file(path),
    }


def resolve_default_db_path() -> Path:
    """从 Memo 配置解析当前数据库路径。"""
    try:
        from memo.core.config import config

        return Path(config.db_path)
    except Exception:
        raw = os.getenv("MEMO_DB_PATH", "")
        if raw:
            p = Path(raw)
            return p if p.is_absolute() else PROJECT_ROOT / p
        return PROJECT_ROOT / "data" / "memo.db"


@dataclass
class ArchivePlan:
    generated_at: str
    dry_run: bool
    project_root: str
    db_path: str
    env_path: str
    backup_dir: str
    db_backup_path: str
    env_backup_path: str | None
    manifest_path: str
    db_exists: bool
    env_exists: bool
    wal_exists: bool
    shm_exists: bool
    service_warning: str
    safety_notes: list[str]


def build_plan(db_path: Path, env_path: Path, backup_dir: Path, dry_run: bool, label: str = "source-aware") -> ArchivePlan:
    ts = stamp()
    db_name = f"memo-before-{label}-{ts}.db"
    env_name = f"env-before-{label}-{ts}.txt"
    manifest_name = f"archive-before-{label}-{ts}.json"
    return ArchivePlan(
        generated_at=iso_now(),
        dry_run=dry_run,
        project_root=str(PROJECT_ROOT),
        db_path=str(db_path),
        env_path=str(env_path),
        backup_dir=str(backup_dir),
        db_backup_path=str(backup_dir / db_name),
        env_backup_path=str(backup_dir / env_name) if env_path.exists() else None,
        manifest_path=str(backup_dir / manifest_name),
        db_exists=db_path.exists(),
        env_exists=env_path.exists(),
        wal_exists=db_path.with_suffix(db_path.suffix + "-wal").exists(),
        shm_exists=db_path.with_suffix(db_path.suffix + "-shm").exists(),
        service_warning="请先停止 Memo 服务后再执行 --apply；如果服务运行中，单独复制 .db 可能不是一致快照。",
        safety_notes=[
            "默认 dry-run 不写任何文件。",
            "--apply 只复制 memo.db 和 .env，不删除、不移动原文件。",
            "检测到 WAL/SHM 只提示风险，不复制、不删除。",
            "真实执行需要 --confirm ARCHIVE。",
        ],
    )


def execute_archive(plan: ArchivePlan) -> dict[str, Any]:
    """执行归档。调用前必须已经确认 dry_run=False 且确认词正确。"""
    db_path = Path(plan.db_path)
    env_path = Path(plan.env_path)
    backup_dir = Path(plan.backup_dir)
    db_backup_path = Path(plan.db_backup_path)
    manifest_path = Path(plan.manifest_path)
    env_backup_path = Path(plan.env_backup_path) if plan.env_backup_path else None

    if not db_path.exists():
        raise FileNotFoundError(f"数据库不存在：{db_path}")

    backup_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(db_path, db_backup_path)
    copied_env = False
    if env_path.exists() and env_backup_path:
        shutil.copy2(env_path, env_backup_path)
        copied_env = True

    result = {
        "plan": asdict(plan),
        "copied": {
            "db": file_info(db_backup_path),
            "env": file_info(env_backup_path) if copied_env and env_backup_path else {"exists": False},
        },
        "original": {
            "db": file_info(db_path),
            "env": file_info(env_path) if env_path.exists() else {"path": str(env_path), "exists": False},
        },
        "wal_shm": {
            "wal": file_info(db_path.with_suffix(db_path.suffix + "-wal")) if plan.wal_exists else {"exists": False},
            "shm": file_info(db_path.with_suffix(db_path.suffix + "-shm")) if plan.shm_exists else {"exists": False},
            "copied": False,
            "deleted": False,
        },
    }
    manifest_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    result["manifest"] = file_info(manifest_path)
    return result


def dry_run_report(plan: ArchivePlan) -> dict[str, Any]:
    db_path = Path(plan.db_path)
    env_path = Path(plan.env_path)
    return {
        "plan": asdict(plan),
        "would_copy": {
            "db": {"from": str(db_path), "to": plan.db_backup_path, **file_info(db_path)},
            "env": ({"from": str(env_path), "to": plan.env_backup_path, **file_info(env_path)} if env_path.exists() else {"exists": False, "path": str(env_path)}),
        },
        "wal_shm": {
            "wal_exists": plan.wal_exists,
            "shm_exists": plan.shm_exists,
            "action": "warn_only_no_copy_no_delete",
        },
    }


def print_human(result: dict[str, Any], dry_run: bool) -> None:
    plan = result["plan"]
    print("=" * 72)
    print("Memo 当前数据库归档工具")
    print("=" * 72)
    print(f"模式：{'DRY-RUN（未写文件）' if dry_run else 'APPLY（已复制归档）'}")
    print(f"项目目录：{plan['project_root']}")
    print(f"数据库：{plan['db_path']}")
    print(f".env：{plan['env_path']}")
    print(f"备份目录：{plan['backup_dir']}")
    print(f"数据库存在：{plan['db_exists']}")
    print(f".env 存在：{plan['env_exists']}")
    print(f"WAL 存在：{plan['wal_exists']} / SHM 存在：{plan['shm_exists']}")
    print(f"提示：{plan['service_warning']}")
    print("\n安全说明：")
    for item in plan["safety_notes"]:
        print(f"- {item}")

    if dry_run:
        copy = result["would_copy"]
        print("\n将复制：")
        db = copy["db"]
        print(f"- DB: {db.get('from')} -> {db.get('to')}")
        print(f"  exists={db.get('exists')} size={db.get('size')} sha256={db.get('sha256')}")
        env = copy["env"]
        if env.get("exists"):
            print(f"- ENV: {env.get('from')} -> {env.get('to')}")
            print(f"  exists={env.get('exists')} size={env.get('size')} sha256={env.get('sha256')}")
        else:
            print("- ENV: 不存在，跳过")
        print("\n真实执行命令：")
        print("python scripts/archive_current_db.py --apply --confirm ARCHIVE")
    else:
        copied = result["copied"]
        print("\n已复制：")
        print(f"- DB: {copied['db'].get('path')}")
        print(f"  size={copied['db'].get('size')} sha256={copied['db'].get('sha256')}")
        if copied["env"].get("exists"):
            print(f"- ENV: {copied['env'].get('path')}")
            print(f"  size={copied['env'].get('size')} sha256={copied['env'].get('sha256')}")
        print(f"- Manifest: {result['manifest'].get('path')}")


def main() -> int:
    parser = argparse.ArgumentParser(description="归档当前 Memo 数据库。默认 dry-run，不写文件。")
    parser.add_argument("--apply", action="store_true", help="真实复制归档。必须同时传 --confirm ARCHIVE。")
    parser.add_argument("--confirm", default="", help="真实执行确认词：ARCHIVE")
    parser.add_argument("--db-path", default="", help="指定数据库路径。默认读取 Memo config.db_path。")
    parser.add_argument("--env-path", default=str(PROJECT_ROOT / ".env"), help="指定 .env 路径。默认项目 .env。")
    parser.add_argument("--backup-dir", default=str(DEFAULT_BACKUP_DIR), help="备份目录。")
    parser.add_argument("--label", default="source-aware", help="备份文件标签。")
    parser.add_argument("--json", action="store_true", help="输出 JSON。")
    args = parser.parse_args()

    dry_run = not args.apply
    if args.apply and args.confirm != CONFIRM_WORD:
        print("拒绝执行：真实归档必须传入 --confirm ARCHIVE。", file=sys.stderr)
        return 2

    db_path = Path(args.db_path) if args.db_path else resolve_default_db_path()
    env_path = Path(args.env_path)
    backup_dir = Path(args.backup_dir)
    plan = build_plan(db_path=db_path, env_path=env_path, backup_dir=backup_dir, dry_run=dry_run, label=args.label)

    try:
        result = dry_run_report(plan) if dry_run else execute_archive(plan)
    except Exception as exc:
        print(f"归档失败：{exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_human(result, dry_run=dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
