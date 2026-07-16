"""Backfill exact duplicate memory rows into merge chains.

默认 dry-run，只报告不写库；加 --apply 后会把同一 normalized raw_text 下的非主记忆
MERGED_INTO 到 canonical，并把 source memory 标为 muted。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from memo.core.engine import engine  # noqa: E402
from memo.dedupe.normalizer import normalize_conversation, stable_hash  # noqa: E402
from memo.store.database import db  # noqa: E402


def _rank_memory(row: dict) -> tuple:
    type_rank = {"DECISION": 0, "PREFERENCE": 1, "FACT": 2, "REASONING": 3, "EVENT": 4}
    status_rank = {"active": 0, "expired": 1, "wrong": 2, "muted": 3, "deleted": 9}
    return (
        status_rank.get(str(row.get("status") or "active"), 5),
        type_rank.get(str(row.get("memory_type") or "FACT").upper(), 9),
        -float(row.get("confidence") or 0),
        row.get("created_at") or "",
    )


def collect_groups(limit: int = 10000) -> list[dict]:
    rows = db.fetchall(
        """SELECT id,title,summary,memory_type,status,confidence,created_at,raw_text
           FROM memory_units
           WHERE raw_text IS NOT NULL AND trim(raw_text) != '' AND COALESCE(status,'active') != 'deleted'
           ORDER BY created_at ASC
           LIMIT ?""",
        (limit,),
    )
    groups: dict[str, dict] = {}
    for r in rows:
        d = dict(r)
        normalized = normalize_conversation(d.get("raw_text") or "")
        if not normalized:
            continue
        key = stable_hash(normalized)
        g = groups.setdefault(key, {"source_hash": key, "preview": normalized[:180], "members": []})
        d.pop("raw_text", None)
        g["members"].append(d)

    duplicates = []
    for g in groups.values():
        if len(g["members"]) <= 1:
            continue
        members = sorted(g["members"], key=_rank_memory)
        g["canonical"] = members[0]
        g["duplicates"] = members[1:]
        duplicates.append(g)
    duplicates.sort(key=lambda g: len(g["members"]), reverse=True)
    return duplicates


def already_linked(source_id: str, target_id: str) -> bool:
    row = db.fetchone(
        """SELECT id FROM memory_links
           WHERE source_memory_id = ? AND target_memory_id = ? AND relation_type = 'MERGED_INTO'
           LIMIT 1""",
        (source_id, target_id),
    )
    return bool(row)


def apply_backfill(groups: list[dict]) -> int:
    merged = 0
    for g in groups:
        target = g["canonical"]["id"]
        for source in g["duplicates"]:
            sid = source["id"]
            if sid == target or already_linked(sid, target):
                continue
            engine.memory_link(
                source_memory_id=sid,
                target_memory_id=target,
                relation_type="MERGED_INTO",
                confidence=1.0,
                reason="backfill exact normalized raw_text duplicate",
                created_by="backfill_duplicate_memories",
            )
            merged += 1
    return merged


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="实际写入 MERGED_INTO 合并链；默认只预览")
    parser.add_argument("--limit", type=int, default=10000, help="最多扫描多少条 memory_units")
    parser.add_argument("--show", type=int, default=20, help="预览多少组重复")
    args = parser.parse_args()

    engine.init()
    groups = collect_groups(limit=args.limit)
    duplicate_rows = sum(len(g["duplicates"]) for g in groups)
    print(f"exact duplicate source groups: {len(groups)}")
    print(f"duplicate rows to merge: {duplicate_rows}")

    for g in groups[: args.show]:
        c = g["canonical"]
        print("-" * 72)
        print(f"source_hash: {g['source_hash'][:16]} count={len(g['members'])}")
        print(f"canonical: {c['id'][:8]} {c.get('memory_type')} {c.get('title')}")
        for d in g["duplicates"]:
            print(f"  merge: {d['id'][:8]} {d.get('memory_type')} {d.get('status')} {d.get('title')}")

    if args.apply:
        merged = apply_backfill(groups)
        print(f"applied merged links: {merged}")
    else:
        print("dry-run only. Use --apply to write merge links.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
