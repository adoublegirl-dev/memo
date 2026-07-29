"""Backfill missing raw turn content from local Agent session files.

This repairs legacy source-only imports that stored turn metadata/hash but not
source_turns.content. It is NOT part of normal future imports: insert_turns()
now writes content directly.

Safety rules:
- default is dry-run;
- only updates rows whose content is empty;
- requires turn_index + role + content_hash match (or an explicitly blank old hash);
- never deletes, moves, or overwrites non-empty content;
- writes a JSON audit report for every apply.

Usage:
  python scripts/backfill_source_turn_content.py --session-id ss_xxx
  python scripts/backfill_source_turn_content.py --all --apply --confirm BACKFILL_CONTENT
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from source_aware_import import HanaAgentAdapter, WorkBuddyAdapter, CodexAdapter

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "memo_source_aware.db"
BACKUP_DIR = PROJECT_ROOT / "data" / "backups"
CONFIRM_TOKEN = "BACKFILL_CONTENT"


def adapter_for_agent(agent: str):
    normalized = (agent or "").strip().lower()
    if normalized == "hanaagent":
        return HanaAgentAdapter()
    if normalized == "workbuddy":
        return WorkBuddyAdapter()
    if normalized == "codex":
        return CodexAdapter()
    raise ValueError(f"unsupported source agent: {agent}")


def empty(value: str | None) -> bool:
    return not str(value or "").strip()


def inspect_session(conn: sqlite3.Connection, session: sqlite3.Row) -> dict:
    session_id = session["id"]
    path = Path(session["source_path"] or "")
    base = {
        "session_id": session_id,
        "title": session["display_title"],
        "source_agent": session["source_agent"],
        "source_path": str(path),
        "path_exists": path.is_file(),
        "matched": 0,
        "fillable": 0,
        "already_has_content": 0,
        "mismatched": 0,
        "missing_source_text": 0,
        "updates": [],
        "source_text_by_index": {},
        "issues": [],
    }
    if not path.is_file():
        base["issues"].append("source file not found")
        return base
    try:
        draft = adapter_for_agent(session["source_agent"]).load_session(path)
    except Exception as exc:
        base["issues"].append(f"parse failed: {type(exc).__name__}: {exc}")
        return base

    source_turns = {turn.turn_index: turn for turn in draft.turns}
    rows = conn.execute(
        """SELECT id, turn_index, role, content, content_hash, source_event_type
           FROM source_turns WHERE source_session_id=? ORDER BY turn_index""",
        (session_id,),
    ).fetchall()
    for row in rows:
        item = dict(row)
        source = source_turns.get(item["turn_index"])
        if source is None:
            base["mismatched"] += 1
            base["issues"].append(f"turn {item['turn_index']}: source turn missing")
            continue
        if source.role != item["role"]:
            base["mismatched"] += 1
            base["issues"].append(f"turn {item['turn_index']}: role mismatch db={item['role']} source={source.role}")
            continue
        if item["content_hash"] and source.content_hash and item["content_hash"] != source.content_hash:
            base["mismatched"] += 1
            base["issues"].append(f"turn {item['turn_index']}: content hash mismatch")
            continue
        base["matched"] += 1
        if not empty(item["content"]):
            base["already_has_content"] += 1
            continue
        if empty(source.text):
            base["missing_source_text"] += 1
            continue
        base["fillable"] += 1
        base["source_text_by_index"][str(item["turn_index"])] = source.text
        base["updates"].append({"turn_id": item["id"], "turn_index": item["turn_index"], "role": item["role"], "content_hash": source.content_hash, "content_length": len(source.text)})
    return base


def backup_database() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = BACKUP_DIR / f"memo-before-content-backfill-{stamp}.db"
    shutil.copy2(DB_PATH, target)
    return target


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--session-id")
    group.add_argument("--all", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--summary", action="store_true", help="只输出全量审计汇总，不输出逐会话明细。")
    parser.add_argument("--limit", type=int, default=0, help="每次最多扫描/回填的会话数；0 表示全部。")
    parser.add_argument("--offset", type=int, default=0, help="按更新时间排序后的会话偏移量，用于分批继续。")
    args = parser.parse_args()
    if args.apply and args.confirm != CONFIRM_TOKEN:
        print(json.dumps({"ok": False, "error": f"apply requires --confirm {CONFIRM_TOKEN}"}, ensure_ascii=False))
        return 2

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # Full repair only considers sessions that still have at least one empty turn.
    # Do not waste time reparsing sessions whose content was already imported.
    if args.session_id:
        where, params = "WHERE ss.id=?", (args.session_id,)
    else:
        where, params = """WHERE EXISTS (
            SELECT 1 FROM source_turns st
            WHERE st.source_session_id=ss.id
              AND st.role IN ('user', 'assistant')
              AND length(trim(COALESCE(st.content, '')))=0
              AND COALESCE(CAST(json_extract(st.metadata_json, '$.content_length') AS INTEGER), 0) > 0
        )""", ()
    limit_sql = "" if args.session_id or not args.limit else " LIMIT ? OFFSET ?"
    query_params = params if args.session_id or not args.limit else params + (max(1, args.limit), max(0, args.offset))
    sessions = conn.execute(f"""SELECT ss.id, ss.display_title, ss.source_agent, ss.source_path
                                FROM source_sessions ss {where} ORDER BY ss.updated_at DESC{limit_sql}""", query_params).fetchall()
    reports = [inspect_session(conn, session) for session in sessions]
    planned = sum(item["fillable"] for item in reports)
    summary = {
        "path_missing": sum(1 for item in reports if not item["path_exists"]),
        "parse_failed": sum(1 for item in reports if any(str(issue).startswith("parse failed") for issue in item["issues"])),
        "mismatched_turns": sum(item["mismatched"] for item in reports),
        "missing_source_text_turns": sum(item["missing_source_text"] for item in reports),
        "already_has_content_turns": sum(item["already_has_content"] for item in reports),
        "by_agent": {},
    }
    for item in reports:
        bucket = summary["by_agent"].setdefault(item["source_agent"] or "unknown", {"sessions": 0, "fillable": 0, "mismatched": 0, "path_missing": 0})
        bucket["sessions"] += 1
        bucket["fillable"] += item["fillable"]
        bucket["mismatched"] += item["mismatched"]
        bucket["path_missing"] += int(not item["path_exists"])
    result = {"ok": True, "dry_run": not args.apply, "session_offset": max(0, args.offset), "session_limit": args.limit or "all", "sessions": len(reports), "planned_updates": planned, "summary": summary, "reports": [] if args.summary else reports}

    if args.apply:
        backup = backup_database()
        updated = 0
        for report in reports:
            for update in report["updates"]:
                text = report["source_text_by_index"][str(update["turn_index"])]
                cursor = conn.execute(
                    """UPDATE source_turns SET content=?, content_hash=?
                       WHERE id=? AND length(trim(COALESCE(content, '')))=0""",
                    (text, update["content_hash"], update["turn_id"]),
                )
                updated += cursor.rowcount
        conn.commit()
        result.update({"dry_run": False, "backup": str(backup), "updated": updated})
    # Raw source text is only used for the immediate update and must never be written into reports.
    for report in reports:
        report.pop("source_text_by_index", None)
    if args.apply:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        audit = BACKUP_DIR / f"content-backfill-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
        audit.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        result["audit"] = str(audit)
    conn.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
