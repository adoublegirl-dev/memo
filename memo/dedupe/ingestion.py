"""Ingestion event gate.

Tracks input chunks before they become memories, so watcher/import/MCP retry paths can be
idempotent.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from memo.dedupe.normalizer import normalize_conversation, stable_hash
from memo.store.database import db, json_encode, new_id


def conversation_hash(text: str) -> str:
    normalized = normalize_conversation(text)
    return stable_hash(normalized) if normalized else ""


def message_hash(text: str) -> str:
    # source_message_hash is intentionally the same normalized hash for now; keeping
    # a separate name leaves room for source-specific ranges later.
    return conversation_hash(text)


def check_ingestion(
    conversation: str,
    source_type: str = "mcp",
    source_agent: str = "",
    source_session_id: str = "",
) -> dict[str, Any]:
    ch = conversation_hash(conversation)
    mh = message_hash(conversation)
    if not ch:
        return {"duplicate": False, "conversation_hash": ch, "source_message_hash": mh}

    row = db.fetchone(
        """SELECT * FROM ingestion_events
           WHERE conversation_hash = ? AND status IN ('processed', 'skipped')
           ORDER BY created_at DESC LIMIT 1""",
        (ch,),
    )
    if row:
        return {
            "duplicate": True,
            "existing_event_id": row["id"],
            "processed_memory_id": row["processed_memory_id"],
            "reason": "conversation_hash_duplicate",
            "conversation_hash": ch,
            "source_message_hash": mh,
        }
    return {"duplicate": False, "conversation_hash": ch, "source_message_hash": mh}


def record_ingestion(
    conversation: str,
    source_type: str = "mcp",
    source_agent: str = "",
    source_session_id: str = "",
    processed_memory_id: str | None = None,
    status: str = "processed",
    reason: str = "",
    metadata: dict[str, Any] | None = None,
) -> str:
    eid = new_id()
    ch = conversation_hash(conversation)
    mh = message_hash(conversation)
    db.execute(
        """INSERT OR IGNORE INTO ingestion_events
           (id, source_type, source_agent, source_session_id, source_message_hash,
            conversation_hash, processed_memory_id, status, reason, metadata_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            eid,
            source_type or "unknown",
            source_agent or "",
            source_session_id or "",
            mh,
            ch,
            processed_memory_id,
            status,
            reason,
            json_encode(metadata or {}),
            datetime.now().isoformat(),
        ),
    )
    db.commit()
    return eid


def recent_ingestion_events(limit: int = 50, status: str = "") -> list[dict[str, Any]]:
    if status:
        rows = db.fetchall(
            "SELECT * FROM ingestion_events WHERE status = ? ORDER BY created_at DESC LIMIT ?",
            (status, limit),
        )
    else:
        rows = db.fetchall("SELECT * FROM ingestion_events ORDER BY created_at DESC LIMIT ?", (limit,))
    return [dict(r) for r in rows]
