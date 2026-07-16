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
            embedding=emb,
            created_at=row["created_at"] or "",
        )


# 全局单例
memory_store = MemoryStore()
