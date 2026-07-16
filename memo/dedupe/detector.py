"""入库去重检测与记录。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from memo.dedupe.normalizer import normalize_conversation, stable_hash, structured_action_key
from memo.store.database import db, new_id

NEAR_DUP_WINDOW_MINUTES = 10


@dataclass
class DedupeDecision:
    action: str  # create / skip / merge_candidate
    reason: str = ""
    existing_memory_id: str | None = None
    existing_record_id: str | None = None
    normalized_hash: str = ""
    raw_hash: str = ""
    fact_key: str = ""
    action_key: str = ""
    entity_key: str = ""

    @property
    def should_skip(self) -> bool:
        return self.action == "skip"

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "reason": self.reason,
            "existing_memory_id": self.existing_memory_id,
            "existing_record_id": self.existing_record_id,
            "normalized_hash": self.normalized_hash,
            "raw_hash": self.raw_hash,
            "fact_key": self.fact_key,
            "action_key": self.action_key,
            "entity_key": self.entity_key,
        }


def _fingerprints(raw_text: str, title: str = "", summary: str = "") -> dict[str, str]:
    normalized = normalize_conversation(raw_text)
    raw_hash = stable_hash(raw_text or "")
    normalized_hash = stable_hash(normalized) if normalized else ""
    action_key, entity_key, fact_key = structured_action_key(raw_text, title, summary)
    return {
        "raw_hash": raw_hash,
        "normalized_hash": normalized_hash,
        "fact_key": fact_key,
        "action_key": action_key,
        "entity_key": entity_key,
    }


def _table_exists() -> bool:
    row = db.fetchone("SELECT name FROM sqlite_master WHERE type='table' AND name='memory_dedupe_records'")
    return bool(row)


def check_before_extract(raw_text: str, session_id: str = "", source_agent: str = "") -> DedupeDecision:
    """LLM 提取前检查 exact / structured duplicates，尽量省 token。"""
    fp = _fingerprints(raw_text)
    if not fp["normalized_hash"] or not _table_exists():
        return DedupeDecision(action="create", **fp)

    row = db.fetchone(
        """SELECT id, memory_id, reason FROM memory_dedupe_records
           WHERE normalized_hash = ? AND decision = 'created'
           ORDER BY created_at DESC LIMIT 1""",
        (fp["normalized_hash"],),
    )
    if row:
        return DedupeDecision(
            action="skip",
            reason="exact_normalized_duplicate",
            existing_memory_id=row["memory_id"],
            existing_record_id=row["id"],
            **fp,
        )

    if fp["action_key"]:
        row = db.fetchone(
            f"""SELECT id, memory_id FROM memory_dedupe_records
                WHERE action_key = ? AND decision = 'created'
                  AND created_at >= datetime('now', '-{NEAR_DUP_WINDOW_MINUTES} minutes')
                ORDER BY created_at DESC LIMIT 1""",
            (fp["action_key"],),
        )
        if row:
            return DedupeDecision(
                action="skip",
                reason="structured_action_duplicate",
                existing_memory_id=row["memory_id"],
                existing_record_id=row["id"],
                **fp,
            )

    return DedupeDecision(action="create", **fp)


def check_after_extract(raw_text: str, title: str, summary: str, memory_type: str = "") -> DedupeDecision:
    """LLM 提取后按事实 key / title-summary 指纹检查近重复。"""
    fp = _fingerprints(raw_text, title, summary)
    if not _table_exists():
        return DedupeDecision(action="create", **fp)

    # 同一事实 key 在短时间窗口内重复，多半来自自动同步/重试。
    if fp["fact_key"]:
        row = db.fetchone(
            f"""SELECT id, memory_id FROM memory_dedupe_records
                WHERE fact_key = ? AND decision = 'created'
                  AND created_at >= datetime('now', '-{NEAR_DUP_WINDOW_MINUTES} minutes')
                ORDER BY created_at DESC LIMIT 1""",
            (fp["fact_key"],),
        )
        if row:
            return DedupeDecision(
                action="skip",
                reason="near_fact_duplicate",
                existing_memory_id=row["memory_id"],
                existing_record_id=row["id"],
                **fp,
            )

    # 标题 + 摘要高度一致也跳过。这里不用 LLM，保持保守。
    title_summary_hash = stable_hash(normalize_conversation(f"{title}\n{summary}"))
    if title_summary_hash:
        row = db.fetchone(
            f"""SELECT id, memory_id FROM memory_dedupe_records
                WHERE fact_key = ? AND decision = 'created'
                  AND created_at >= datetime('now', '-{NEAR_DUP_WINDOW_MINUTES} minutes')
                ORDER BY created_at DESC LIMIT 1""",
            (f"ts:{title_summary_hash[:16]}",),
        )
        if row:
            return DedupeDecision(
                action="skip",
                reason="title_summary_duplicate",
                existing_memory_id=row["memory_id"],
                existing_record_id=row["id"],
                **{**fp, "fact_key": f"ts:{title_summary_hash[:16]}"},
            )
        if not fp["fact_key"]:
            fp["fact_key"] = f"ts:{title_summary_hash[:16]}"

    return DedupeDecision(action="create", **fp)


def record_created(memory_id: str, raw_text: str, title: str = "", summary: str = "", session_id: str = "", source_agent: str = "") -> None:
    if not _table_exists():
        return
    fp = _fingerprints(raw_text, title, summary)
    title_summary_hash = stable_hash(normalize_conversation(f"{title}\n{summary}"))
    fact_key = fp["fact_key"] or (f"ts:{title_summary_hash[:16]}" if title_summary_hash else "")
    db.execute(
        """INSERT OR IGNORE INTO memory_dedupe_records
           (id, memory_id, session_id, source_agent, raw_hash, normalized_hash, fact_key, action_key, entity_key, decision, reason, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'created', '', ?)""",
        (
            new_id(), memory_id, session_id or "", source_agent or "",
            fp["raw_hash"], fp["normalized_hash"], fact_key,
            fp["action_key"], fp["entity_key"], datetime.now().isoformat(),
        ),
    )
    # 同步记录 title/summary 指纹，便于不同 raw_text 的同事实去重。
    if title_summary_hash:
        db.execute(
            """INSERT OR IGNORE INTO memory_dedupe_records
               (id, memory_id, session_id, source_agent, raw_hash, normalized_hash, fact_key, action_key, entity_key, decision, reason, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'created', 'title_summary_alias', ?)""",
            (
                new_id(), memory_id, session_id or "", source_agent or "",
                fp["raw_hash"], fp["normalized_hash"], f"ts:{title_summary_hash[:16]}",
                fp["action_key"], fp["entity_key"], datetime.now().isoformat(),
            ),
        )
    db.commit()


def record_skipped(decision: DedupeDecision, session_id: str = "", source_agent: str = "") -> None:
    if not _table_exists():
        return
    db.execute(
        """INSERT INTO memory_dedupe_records
           (id, memory_id, session_id, source_agent, raw_hash, normalized_hash, fact_key, action_key, entity_key, decision, reason, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'skipped', ?, ?)""",
        (
            new_id(), decision.existing_memory_id, session_id or "", source_agent or "",
            decision.raw_hash, decision.normalized_hash, decision.fact_key,
            decision.action_key, decision.entity_key, decision.reason, datetime.now().isoformat(),
        ),
    )
    db.commit()
