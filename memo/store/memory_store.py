"""记忆单元存储层 —— CRUD 操作。"""

from datetime import datetime
from typing import Any

import numpy as np

from memo.models import MemoryUnit, MemoryType, Session, SessionStatus
from memo.store.database import blob_decode, blob_encode, db, json_decode, json_encode, new_id
from memo.utils.logger import logger


class MemoryStore:
    """记忆单元 + 会话的存储层。"""

    def __init__(self):
        pass

    # ── 会话 ──

    def create_session(
        self,
        agent_id: str = "default",
        title: str = "",
        space_id: str | None = None,
    ) -> Session:
        session_id = new_id()
        now = datetime.now().isoformat()
        db.execute(
            """INSERT INTO sessions (id, agent_id, title, created_at, space_id)
               VALUES (?, ?, ?, ?, NULLIF(?, ''))""",
            (session_id, agent_id, title, now, space_id or ""),
        )
        db.commit()
        return Session(
            id=session_id,
            agent_id=agent_id,
            title=title,
            created_at=now,
            space_id=space_id or "",
        )

    def end_session(self, session_id: str) -> None:
        now = datetime.now().isoformat()
        db.execute(
            "UPDATE sessions SET status = 'completed', ended_at = ? WHERE id = ?",
            (now, session_id),
        )
        db.commit()

    # ── 记忆单元 ──

    def add_memory(
        self,
        session_id: str,
        title: str = "",
        summary: str = "",
        summary_detail: str = "",
        raw_text: str = "",
        memory_type: MemoryType = MemoryType.FACT,
        confidence: float = 0.8,
        valid_from: str = "",
        valid_until: str = "",
        signal_level: int = 0,
    ) -> str:
        """添加记忆单元，返回 ID。"""
        memory_id = new_id()
        now = datetime.now().isoformat()
        db.execute(
            """INSERT INTO memory_units
               (id, session_id, title, summary, summary_detail, raw_text,
                memory_type, confidence, valid_from, valid_until, recorded_at, signal_level)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                memory_id,
                session_id,
                title,
                summary,
                summary_detail,
                raw_text,
                memory_type.value,
                confidence,
                valid_from or now,
                valid_until or None,
                now,
                signal_level,
            ),
        )
        # 更新会话的记忆计数
        db.execute(
            "UPDATE sessions SET memory_count = memory_count + 1 WHERE id = ?",
            (session_id,),
        )
        db.commit()
        return memory_id

    def get_memory(self, memory_id: str) -> MemoryUnit | None:
        row = db.fetchone("SELECT * FROM memory_units WHERE id = ?", (memory_id,))
        return self._row_to_memory(row) if row else None

    def get_memories_batch(self, memory_ids: list[str]) -> list[MemoryUnit]:
        if not memory_ids:
            return []
        placeholders = ",".join("?" * len(memory_ids))
        rows = db.fetchall(
            f"SELECT * FROM memory_units WHERE id IN ({placeholders})", memory_ids
        )
        return [self._row_to_memory(r) for r in rows]

    def get_session_memories(self, session_id: str) -> list[MemoryUnit]:
        rows = db.fetchall(
            "SELECT * FROM memory_units WHERE session_id = ? ORDER BY created_at",
            (session_id,),
        )
        return [self._row_to_memory(r) for r in rows]

    def supersede_memory(self, old_id: str, new_id: str) -> None:
        """将旧记忆标记为已被新记忆替代（双时序处理）。"""
        db.execute(
            "UPDATE memory_units SET is_superseded = 1, superseded_by = ?, valid_until = datetime('now') WHERE id = ?",
            (new_id, old_id),
        )
        db.commit()

    # ── 记忆治理 ──

    def govern_memory(
        self,
        memory_id: str,
        action: str,
        actor: str = "dashboard",
        note: str = "",
        status: str | None = None,
        user_weight: float | None = None,
        pinned: bool | None = None,
        user_note: str | None = None,
    ) -> dict:
        """用户侧记忆治理：标重要、错误、过期、静默、软删除、恢复、备注。"""
        row = db.fetchone("SELECT * FROM memory_units WHERE id = ?", (memory_id,))
        if not row:
            return {"error": "memory not found"}

        now = datetime.now().isoformat()
        updates: dict[str, Any] = {}

        if action == "pin":
            updates["pinned"] = 1
            updates["user_weight"] = user_weight if user_weight is not None else max(float(row["user_weight"]), 1.5)
        elif action == "unpin":
            updates["pinned"] = 0
        elif action == "mark_wrong":
            updates["status"] = "wrong"
            updates["user_weight"] = 0.0
        elif action == "mark_expired":
            updates["status"] = "expired"
            updates["user_weight"] = 0.2
            updates["valid_until"] = now
        elif action == "mute":
            updates["status"] = "muted"
            updates["user_weight"] = 0.0
        elif action == "delete":
            updates["status"] = "deleted"
            updates["user_weight"] = 0.0
        elif action == "restore":
            updates["status"] = "active"
            updates["user_weight"] = user_weight if user_weight is not None else 1.0
            updates["valid_until"] = None
        elif action == "update":
            if status is not None:
                updates["status"] = status
            if user_weight is not None:
                updates["user_weight"] = user_weight
            if pinned is not None:
                updates["pinned"] = 1 if pinned else 0
            if user_note is not None:
                updates["user_note"] = user_note
        else:
            return {"error": f"unknown memory action: {action}"}

        if user_note is not None and action != "update":
            updates["user_note"] = user_note
        updates["updated_at"] = now

        for key, value in updates.items():
            old_value = row[key] if key in row.keys() else ""
            db.execute(f"UPDATE memory_units SET {key} = ? WHERE id = ?", (value, memory_id))
            self._audit(memory_id, key, old_value, value, actor, note or action)
        db.commit()
        return {"id": memory_id, "action": action, "updated": True, "fields": updates}

    def _audit(self, memory_id: str, action: str, old_value: Any, new_value: Any, actor: str, note: str = "") -> None:
        db.execute(
            """INSERT INTO memory_audit_logs (memory_id, action, old_value, new_value, actor, note, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (memory_id, action, str(old_value or ""), str(new_value or ""), actor, note, datetime.now().isoformat()),
        )

    def get_memory_audit(self, memory_id: str, limit: int = 50) -> list[dict]:
        rows = db.fetchall(
            "SELECT * FROM memory_audit_logs WHERE memory_id = ? ORDER BY created_at DESC LIMIT ?",
            (memory_id, limit),
        )
        return [dict(r) for r in rows]

    def link_memories(
        self,
        source_memory_id: str,
        target_memory_id: str,
        relation_type: str = "MERGED_INTO",
        confidence: float = 0.8,
        reason: str = "",
        created_by: str = "system",
    ) -> dict:
        """建立记忆间治理关系，如 MERGED_INTO / REFINE / SUPERSEDE。"""
        link_id = new_id()
        db.execute(
            """INSERT OR IGNORE INTO memory_links
               (id, source_memory_id, target_memory_id, relation_type, confidence, reason, created_by, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                link_id,
                source_memory_id,
                target_memory_id,
                relation_type,
                confidence,
                reason,
                created_by,
                datetime.now().isoformat(),
            ),
        )
        if relation_type.upper() == "MERGED_INTO":
            db.execute("UPDATE memory_units SET status='muted', updated_at=? WHERE id=?", (datetime.now().isoformat(), source_memory_id))
            self._audit(source_memory_id, "merged_into", "", target_memory_id, created_by, reason)
        db.commit()
        return {"source_memory_id": source_memory_id, "target_memory_id": target_memory_id, "relation_type": relation_type, "linked": True}

    def get_memory_links(self, memory_id: str, limit: int = 50) -> list[dict]:
        rows = db.fetchall(
            """SELECT * FROM memory_links
               WHERE source_memory_id = ? OR target_memory_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (memory_id, memory_id, limit),
        )
        return [dict(r) for r in rows]

    def _row_to_memory(self, row) -> MemoryUnit:
        emb = blob_decode(row["embedding"]) if row["embedding"] else None
        return MemoryUnit(
            id=row["id"],
            session_id=row["session_id"],
            title=row["title"],
            summary=row["summary"],
            summary_detail=row["summary_detail"],
            raw_text=row["raw_text"],
            valid_from=row["valid_from"] or "",
            valid_until=row["valid_until"] or "",
            recorded_at=row["recorded_at"] or "",
            is_superseded=bool(row["is_superseded"]),
            superseded_by=row["superseded_by"] or "",
            confidence=row["confidence"],
            memory_type=row["memory_type"],
            signal_level=row["signal_level"] if "signal_level" in row.keys() else 0,
            status=row["status"] if "status" in row.keys() else "active",
            user_weight=row["user_weight"] if "user_weight" in row.keys() else 1.0,
            pinned=bool(row["pinned"]) if "pinned" in row.keys() else False,
            user_note=row["user_note"] if "user_note" in row.keys() else "",
            updated_at=row["updated_at"] if "updated_at" in row.keys() and row["updated_at"] else "",
            embedding=emb,
            created_at=row["created_at"] or "",
        )


# 全局单例
memory_store = MemoryStore()
