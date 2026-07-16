"""Context Space 管理器。

Space 是软边界：它组织和加权记忆，但不切断全局图谱与跨域联想。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from memo.store.database import blob_encode, db, json_encode, new_id
from memo.utils.embedding import embedding_model
from memo.utils.logger import logger


class SpaceManager:
    """Space 生命周期与绑定管理。"""

    def create(
        self,
        name: str,
        type: str = "general",
        description: str = "",
        goal: str = "",
        aliases: list[str] | None = None,
        profile: dict[str, Any] | None = None,
        created_by: str = "manual",
    ) -> dict:
        """创建 Space。已存在同名 Space 时返回已有记录。"""
        existing = self.get_by_name(name)
        if existing:
            return {**existing, "created": False}

        sid = new_id()
        now = datetime.now().isoformat()
        text_for_embedding = " ".join([name, type, description, goal]).strip() or name
        emb = embedding_model.encode(text_for_embedding)
        db.execute(
            """INSERT INTO spaces (
                id, name, type, description, goal, profile_json, centroid_embedding,
                created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                sid,
                name,
                type or "general",
                description,
                goal,
                json_encode(profile or {}),
                blob_encode(emb),
                created_by,
                now,
                now,
            ),
        )
        for alias in aliases or []:
            self.add_alias(sid, alias)
        db.commit()
        logger.info(f"Space 已创建: {name} ({sid[:8]})")
        return {**self.get(sid), "created": True}

    def update(self, space_id: str, **fields) -> dict:
        """更新 Space 基础字段。"""
        space = self.resolve(space_id)
        if not space:
            return {"error": "space not found"}
        sid = space["id"]
        allowed = {
            "name", "type", "description", "goal", "background", "current_state",
            "next_action", "priority", "status", "profile_json",
        }
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not updates:
            return {**space, "updated": False}

        updates["updated_at"] = datetime.now().isoformat()
        set_sql = ", ".join(f"{k} = ?" for k in updates)
        db.execute(f"UPDATE spaces SET {set_sql} WHERE id = ?", tuple(updates.values()) + (sid,))
        db.commit()
        return {**self.get(sid), "updated": True}

    def list(self, include_archived: bool = False, type: str = "") -> list[dict]:
        """列出 Space 摘要。"""
        conditions = []
        params: list[Any] = []
        if not include_archived:
            conditions.append("status != 'archived'")
        if type:
            conditions.append("type = ?")
            params.append(type)
        where = " AND ".join(conditions) if conditions else "1=1"
        rows = db.fetchall(
            f"""SELECT * FROM spaces WHERE {where}
                ORDER BY is_default DESC, updated_at DESC, name ASC""",
            tuple(params),
        )
        return [self._row_to_dict(r) for r in rows]

    def get(self, space_id: str) -> dict | None:
        row = db.fetchone("SELECT * FROM spaces WHERE id = ?", (space_id,))
        return self._row_to_dict(row) if row else None

    def get_by_name(self, name: str) -> dict | None:
        row = db.fetchone("SELECT * FROM spaces WHERE name = ?", (name,))
        return self._row_to_dict(row) if row else None

    def get_default(self) -> dict | None:
        row = db.fetchone("SELECT * FROM spaces WHERE is_default = 1 ORDER BY created_at LIMIT 1")
        return self._row_to_dict(row) if row else None

    def resolve(self, space_id_or_name: str) -> dict | None:
        """按 id、name、alias 解析 Space。"""
        if not space_id_or_name:
            return None
        direct = self.get(space_id_or_name) or self.get_by_name(space_id_or_name)
        if direct:
            return direct
        row = db.fetchone(
            """SELECT s.* FROM spaces s
               JOIN space_aliases a ON a.space_id = s.id
               WHERE a.alias = ? LIMIT 1""",
            (space_id_or_name,),
        )
        return self._row_to_dict(row) if row else None

    def add_alias(self, space_id: str, alias: str) -> None:
        if not alias.strip():
            return
        db.execute(
            """INSERT OR IGNORE INTO space_aliases (id, space_id, alias, created_at)
               VALUES (?, ?, ?, ?)""",
            (new_id(), space_id, alias.strip(), datetime.now().isoformat()),
        )

    def bind_memory(
        self,
        space_id: str,
        memory_id: str,
        relation_type: str = "related",
        relevance: float = 0.8,
        created_by: str = "auto",
    ) -> dict:
        """将记忆绑定到 Space。"""
        space = self.resolve(space_id)
        if not space:
            return {"error": "space not found"}
        sid = space["id"]
        now = datetime.now().isoformat()
        db.execute(
            """INSERT OR REPLACE INTO space_memories
               (space_id, memory_id, relation_type, relevance, created_by, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (sid, memory_id, relation_type, relevance, created_by, now),
        )
        self._refresh_counts(sid)
        db.commit()
        return {"space_id": sid, "memory_id": memory_id, "bound": True}

    def bind_todo(self, space_id: str, todo_id: str, relation_type: str = "action") -> dict:
        """将待办绑定到 Space。"""
        space = self.resolve(space_id)
        if not space:
            return {"error": "space not found"}
        sid = space["id"]
        db.execute(
            "UPDATE todos SET space_id = ?, space_relation_type = ?, updated_at = ? WHERE id = ?",
            (sid, relation_type, datetime.now().isoformat(), todo_id),
        )
        self._refresh_counts(sid)
        db.commit()
        return {"space_id": sid, "todo_id": todo_id, "bound": True}

    def archive(self, space_id: str) -> dict:
        space = self.resolve(space_id)
        if not space:
            return {"error": "space not found"}
        now = datetime.now().isoformat()
        db.execute(
            "UPDATE spaces SET status='archived', archived_at=?, updated_at=? WHERE id=?",
            (now, now, space["id"]),
        )
        db.commit()
        return {"id": space["id"], "archived": True}

    def _refresh_counts(self, space_id: str) -> None:
        mem = db.fetchone("SELECT COUNT(*) AS c FROM space_memories WHERE space_id = ?", (space_id,))
        todo = db.fetchone("SELECT COUNT(*) AS c FROM todos WHERE space_id = ?", (space_id,))
        session = db.fetchone("SELECT COUNT(*) AS c FROM sessions WHERE space_id = ?", (space_id,))
        db.execute(
            """UPDATE spaces SET memory_count=?, todo_count=?, session_count=?, updated_at=?
               WHERE id=?""",
            (
                mem["c"] if mem else 0,
                todo["c"] if todo else 0,
                session["c"] if session else 0,
                datetime.now().isoformat(),
                space_id,
            ),
        )

    def _row_to_dict(self, row) -> dict:
        if not row:
            return {}
        data = dict(row)
        # BLOB 不直接暴露给 MCP/Dashboard，避免 JSON 序列化失败。
        data["has_centroid"] = bool(data.get("centroid_embedding"))
        data.pop("centroid_embedding", None)
        return data


space_manager = SpaceManager()
