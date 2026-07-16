"""Context Space 简报生成。"""

from __future__ import annotations

from memo.space.manager import space_manager
from memo.store.database import db, json_decode


class SpaceSummarizer:
    """聚合 Space 的记忆、待办、决策、风险和基础状态。"""

    def summarize(self, space_id: str, mode: str = "brief") -> dict:
        space = space_manager.resolve(space_id)
        if not space:
            return {"error": "space not found"}
        sid = space["id"]

        memories = db.fetchall(
            """SELECT mu.id, mu.title, mu.summary, mu.memory_type, mu.created_at, sm.relation_type, sm.relevance
               FROM space_memories sm
               JOIN memory_units mu ON mu.id = sm.memory_id
               WHERE sm.space_id = ? AND mu.is_superseded = 0
               ORDER BY mu.created_at DESC
               LIMIT 10""",
            (sid,),
        )
        decisions = db.fetchall(
            """SELECT mu.id, mu.title, mu.summary, mu.created_at
               FROM space_memories sm
               JOIN memory_units mu ON mu.id = sm.memory_id
               WHERE sm.space_id = ? AND mu.memory_type = 'DECISION' AND mu.is_superseded = 0
               ORDER BY mu.created_at DESC
               LIMIT 5""",
            (sid,),
        )
        todos = db.fetchall(
            """SELECT * FROM todos
               WHERE space_id = ? AND status IN ('todo', 'doing')
               ORDER BY CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, due_date ASC
               LIMIT 10""",
            (sid,),
        )
        tags = db.fetchall(
            """SELECT ft.name, COUNT(*) AS c
               FROM space_memories sm
               JOIN tag_mentions tm ON tm.memory_unit_id = sm.memory_id
               JOIN feature_tags ft ON ft.id = tm.tag_id
               WHERE sm.space_id = ?
               GROUP BY ft.id
               ORDER BY c DESC
               LIMIT 10""",
            (sid,),
        )

        profile = json_decode(space.get("profile_json", "{}"))
        return {
            "space": space,
            "mode": mode,
            "profile": profile if isinstance(profile, dict) else {},
            "status": {
                "total_memories": space.get("memory_count", 0),
                "active_todos": len(todos),
                "total_sessions": space.get("session_count", 0),
                "last_activity": space.get("last_active_at") or space.get("updated_at"),
            },
            "key_feature_tags": [dict(r) for r in tags],
            "recent_memories": [dict(r) for r in memories],
            "recent_decisions": [dict(r) for r in decisions],
            "active_todos": [dict(r) for r in todos],
        }


space_summarizer = SpaceSummarizer()
