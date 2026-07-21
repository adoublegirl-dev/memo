"""Source Session 来源会话层。

source_sessions 是对真实来源的索引层，不替代 memo.sessions，
也不修改 memory/todo 的权重或内容。当前先提供兼容 memo.sessions 的基础映射，
后续导入/同步链路可直接写入真实外部会话来源。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from memo.dedupe.normalizer import stable_hash
from memo.store.database import db, new_id


def _now() -> str:
    return datetime.now().isoformat()


def _dumps(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=False)


def _loads(text: str | None) -> dict:
    try:
        value = json.loads(text or "{}")
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


class SourceSessionManager:
    """来源会话基础管理。"""

    def ensure_from_session(
        self,
        session: dict,
        memories: list[dict] | None = None,
        todos: list[dict] | None = None,
        commit: bool = True,
    ) -> dict:
        """为现有 memo.sessions 建立 source_sessions 兼容映射。"""
        sid = session.get("id") or ""
        if not sid:
            return {"error": "missing session id"}
        memories = memories or []
        todos = todos or []
        existing = db.fetchone("SELECT * FROM source_sessions WHERE legacy_session_id=?", (sid,))
        now = _now()
        source_agent = session.get("agent_id") or session.get("source_agent") or ""
        title = session.get("title") or ""
        memory_count = len(memories) if memories else int(session.get("memory_count") or 0)
        todo_count = len(todos)
        content_basis = "\n".join(
            [sid, source_agent, title]
            + [m.get("id", "") for m in memories[:80]]
            + [t.get("id", "") for t in todos[:40]]
        )
        payload = (
            "memo_session",
            source_agent,
            sid,
            title,
            session.get("created_at") or "",
            memory_count,
            todo_count,
            stable_hash(content_basis),
            _dumps({
                "memo_session_status": session.get("status", ""),
                "memo_session_memory_count": session.get("memory_count", 0),
                "space_id": session.get("space_id", ""),
            }),
            now,
        )
        if existing:
            source_id = existing["id"]
            db.execute(
                """UPDATE source_sessions SET
                       source_type=?, source_agent=?, external_session_id=?, title=?, started_at=?,
                       memory_count=?, todo_count=?, content_hash=?, metadata_json=?, updated_at=?
                   WHERE id=?""",
                payload + (source_id,),
            )
        else:
            source_id = new_id()
            db.execute(
                """INSERT INTO source_sessions
                   (id, source_type, source_agent, external_session_id, legacy_session_id, title,
                    started_at, memory_count, todo_count, content_hash, metadata_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (source_id, payload[0], payload[1], payload[2], sid, payload[3], payload[4], payload[5], payload[6], payload[7], payload[8], now, now),
            )
        self.bind_memories(source_id, [m.get("id", "") for m in memories], commit=False)
        self.bind_todos(source_id, [t.get("id", "") for t in todos], commit=False)
        if commit:
            db.commit()
        return self.get(source_id) or {"id": source_id}

    def bind_memories(self, source_session_id: str, memory_ids: list[str], commit: bool = True) -> None:
        now = _now()
        for mid in memory_ids:
            if not mid:
                continue
            db.execute(
                """INSERT OR IGNORE INTO source_session_memories
                   (source_session_id, memory_id, relation_type, created_at)
                   VALUES (?, ?, 'originated_from', ?)""",
                (source_session_id, mid, now),
            )
        if commit:
            db.commit()

    def bind_todos(self, source_session_id: str, todo_ids: list[str], commit: bool = True) -> None:
        now = _now()
        for tid in todo_ids:
            if not tid:
                continue
            db.execute(
                """INSERT OR IGNORE INTO source_session_todos
                   (source_session_id, todo_id, relation_type, created_at)
                   VALUES (?, ?, 'originated_from', ?)""",
                (source_session_id, tid, now),
            )
        if commit:
            db.commit()

    def backfill_from_sessions(self, limit: int = 200) -> dict:
        """渐进式从 memo.sessions 建立 source_sessions 映射。"""
        rows = db.fetchall(
            """SELECT s.* FROM sessions s
               WHERE NOT EXISTS (SELECT 1 FROM source_sessions ss WHERE ss.legacy_session_id=s.id)
               ORDER BY s.created_at DESC
               LIMIT ?""",
            (limit,),
        )
        created = 0
        for row in rows:
            session = dict(row)
            memories = [dict(r) for r in db.fetchall(
                """SELECT id FROM memory_units
                   WHERE session_id=? AND COALESCE(status, 'active') NOT IN ('deleted','wrong','muted')""",
                (session["id"],),
            )]
            todos = [dict(r) for r in db.fetchall("SELECT id FROM todos WHERE session_id=?", (session["id"],))]
            self.ensure_from_session(session, memories=memories, todos=todos, commit=False)
            created += 1
        db.commit()
        remaining = db.fetchone(
            """SELECT COUNT(*) AS c FROM sessions s
               WHERE NOT EXISTS (SELECT 1 FROM source_sessions ss WHERE ss.legacy_session_id=s.id)"""
        )
        return {"scanned": len(rows), "created": created, "remaining": int(remaining["c"] if remaining else 0)}

    def list(self, limit: int = 50, source_type: str = "", source_agent: str = "") -> list[dict]:
        where = []
        params: list[Any] = []
        if source_type:
            where.append("source_type=?")
            params.append(source_type)
        if source_agent:
            where.append("source_agent=?")
            params.append(source_agent)
        sql = "SELECT * FROM source_sessions"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        return [self._row_to_dict(r) for r in db.fetchall(sql, tuple(params))]

    def get(self, source_session_id: str) -> dict | None:
        row = db.fetchone("SELECT * FROM source_sessions WHERE id=? OR legacy_session_id=?", (source_session_id, source_session_id))
        if not row:
            return None
        data = self._row_to_dict(row)
        data["memories"] = [dict(r) for r in db.fetchall(
            """SELECT mu.id, mu.title, mu.summary, mu.memory_type, mu.created_at
               FROM source_session_memories ssm
               JOIN memory_units mu ON mu.id=ssm.memory_id
               WHERE ssm.source_session_id=?
               ORDER BY mu.created_at DESC
               LIMIT 50""",
            (data["id"],),
        )]
        data["todos"] = [dict(r) for r in db.fetchall(
            """SELECT t.* FROM source_session_todos sst
               JOIN todos t ON t.id=sst.todo_id
               WHERE sst.source_session_id=?
               ORDER BY t.created_at DESC
               LIMIT 50""",
            (data["id"],),
        )]
        return data

    def stats(self) -> dict:
        total = db.fetchone("SELECT COUNT(*) AS c FROM source_sessions")
        by_type = db.fetchall("SELECT source_type, COUNT(*) AS c FROM source_sessions GROUP BY source_type ORDER BY c DESC")
        by_agent = db.fetchall("SELECT source_agent, COUNT(*) AS c FROM source_sessions GROUP BY source_agent ORDER BY c DESC LIMIT 12")
        unmapped = db.fetchone(
            """SELECT COUNT(*) AS c FROM sessions s
               WHERE NOT EXISTS (SELECT 1 FROM source_sessions ss WHERE ss.legacy_session_id=s.id)"""
        )
        return {
            "total": int(total["c"] if total else 0),
            "by_type": [dict(r) for r in by_type],
            "by_agent": [dict(r) for r in by_agent],
            "unmapped_sessions": int(unmapped["c"] if unmapped else 0),
        }

    def _row_to_dict(self, row) -> dict:
        data = dict(row)
        data["metadata"] = _loads(data.pop("metadata_json", "{}"))
        return data


source_session_manager = SourceSessionManager()
