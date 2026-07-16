"""Context Space 简报生成。"""

from __future__ import annotations

from datetime import datetime

from memo.space.manager import space_manager
from memo.store.database import db, json_decode, json_encode, new_id


class SpaceSummarizer:
    """聚合 Space 的记忆、待办、决策、风险和基础状态。"""

    def summarize(self, space_id: str, mode: str = "brief", persist: bool = False) -> dict:
        space = space_manager.resolve(space_id)
        if not space:
            return {"error": "space not found"}
        sid = space["id"]

        memories = db.fetchall(
            """SELECT mu.id, mu.title, mu.summary, mu.memory_type, mu.created_at, sm.relation_type, sm.relevance
               FROM space_memories sm
               JOIN memory_units mu ON mu.id = sm.memory_id
               WHERE sm.space_id = ? AND mu.is_superseded = 0 AND COALESCE(mu.status,'active') NOT IN ('wrong','deleted','muted')
               ORDER BY mu.created_at DESC
               LIMIT 12""",
            (sid,),
        )
        decisions = db.fetchall(
            """SELECT mu.id, mu.title, mu.summary, mu.created_at
               FROM space_memories sm
               JOIN memory_units mu ON mu.id = sm.memory_id
               WHERE sm.space_id = ? AND mu.memory_type = 'DECISION' AND mu.is_superseded = 0
               ORDER BY mu.created_at DESC
               LIMIT 6""",
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
        payload = {
            "space": space,
            "aliases": space_manager.aliases(sid),
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
        payload["summary_text"] = self._compose_summary(payload, mode)
        if persist:
            db.execute(
                """INSERT INTO space_summaries (id, space_id, mode, summary_text, payload_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (new_id(), sid, mode, payload["summary_text"], json_encode(payload), datetime.now().isoformat()),
            )
            db.commit()
        return payload

    def _compose_summary(self, payload: dict, mode: str) -> str:
        space = payload["space"]
        todos = payload["active_todos"]
        decisions = payload["recent_decisions"]
        memories = payload["recent_memories"]
        tags = payload["key_feature_tags"]
        name = space.get("name", "未命名空间")
        lines = [f"{name} · {mode} 简报"]
        if space.get("goal"):
            lines.append(f"目标：{space['goal']}")
        if tags:
            lines.append("关键词：" + "、".join(t["name"] for t in tags[:6]))
        if decisions:
            lines.append("近期决策：" + "；".join(d["title"] for d in decisions[:3]))
        if todos:
            high = [t for t in todos if t.get("priority") == "high"]
            lines.append(f"待办：{len(todos)} 项进行中，其中高优 {len(high)} 项。")
            lines.append("下一步：" + "；".join(t["title"] for t in todos[:3]))
        elif memories:
            lines.append("下一步：暂无 Space 待办，可根据最近记忆补充行动项。")
        else:
            lines.append("当前空间资料较少，建议先绑定相关记忆或建立待办。")
        if mode == "risk":
            risky = [t for t in todos if t.get("priority") == "high" or t.get("due_date")]
            lines.append("风险关注：" + ("；".join(t["title"] for t in risky[:4]) if risky else "暂无明显高优/截止日期风险。"))
        if mode == "handoff":
            lines.append("交接要点：先看近期决策，再处理高优待办，最后补齐缺失背景。")
        if mode == "weekly":
            lines.append(f"本周脉络：最近记录 {len(memories)} 条，决策 {len(decisions)} 条。")
        return "\n".join(lines)


space_summarizer = SpaceSummarizer()
