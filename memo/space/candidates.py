"""Space Candidate：基于历史会话生成候选项目。

Candidate 是“待用户确认的整理建议”，不直接等同正式 Space。
系统只负责发现和提示，确认/合并/忽略均由用户手动触发。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from memo.core.config import config
from memo.dedupe.normalizer import normalize_conversation
from memo.store.database import db, json_encode, new_id
from memo.space.manager import space_manager
from memo.space.source_sessions import source_session_manager
from memo.utils.llm import llm_client
from memo.utils.logger import logger


def _loads(text: str | None) -> list:
    try:
        value = json.loads(text or "[]")
        return value if isinstance(value, list) else []
    except Exception:
        return []


def _dumps(value: Any) -> str:
    return json.dumps(value or [], ensure_ascii=False)


def _uniq(values: list[str]) -> list[str]:
    seen = set()
    out = []
    for v in values:
        if not v or v in seen:
            continue
        seen.add(v)
        out.append(v)
    return out


def _compact(text: str, limit: int = 180) -> str:
    text = " ".join((text or "").split())
    return text[:limit] + ("..." if len(text) > limit else "")


def _candidate_key(name: str) -> str:
    normalized = normalize_conversation(name or "")
    return normalized[:120] or f"candidate-{new_id()}"


def _session_rows(limit: int = 80) -> list[dict]:
    rows = db.fetchall(
        """SELECT s.*, COUNT(mu.id) AS actual_memory_count
           FROM sessions s
           LEFT JOIN memory_units mu ON mu.session_id = s.id
                AND COALESCE(mu.status, 'active') NOT IN ('deleted','wrong','muted')
           WHERE s.status != 'archived'
             AND NOT EXISTS (
                SELECT 1 FROM space_candidates sc
                WHERE sc.status IN ('pending','accepted','merged','merged_to_existing','ignored','rejected')
                  AND sc.source_session_ids LIKE '%' || s.id || '%'
             )
           GROUP BY s.id
           HAVING actual_memory_count > 0
           ORDER BY s.created_at DESC
           LIMIT ?""",
        (limit,),
    )
    return [dict(r) for r in rows]


def _session_memories(session_id: str, limit: int = 12) -> list[dict]:
    rows = db.fetchall(
        """SELECT id, title, summary, summary_detail, raw_text, memory_type, created_at
           FROM memory_units
           WHERE session_id = ? AND COALESCE(status, 'active') NOT IN ('deleted','wrong','muted')
           ORDER BY created_at DESC
           LIMIT ?""",
        (session_id, limit),
    )
    return [dict(r) for r in rows]


def _session_todos(session_id: str) -> list[dict]:
    rows = db.fetchall(
        """SELECT id, title, description, priority, status, due_date, created_at
           FROM todos
           WHERE session_id = ?
           ORDER BY created_at DESC
           LIMIT 20""",
        (session_id,),
    )
    return [dict(r) for r in rows]


def _session_tags(memory_ids: list[str], limit: int = 8) -> list[str]:
    if not memory_ids:
        return []
    placeholders = ",".join("?" for _ in memory_ids)
    rows = db.fetchall(
        f"""SELECT ft.name, COUNT(*) AS c
            FROM tag_mentions tm
            JOIN feature_tags ft ON ft.id = tm.tag_id
            WHERE tm.memory_unit_id IN ({placeholders})
            GROUP BY ft.name
            ORDER BY c DESC, MAX(tm.relevance_score) DESC
            LIMIT ?""",
        tuple(memory_ids) + (limit,),
    )
    return [r["name"] for r in rows]


GENERIC_SESSION_TITLES = {"", "自动会话", "自动同步会话", "自动导入会话", "未命名会话", "新会话"}


def _is_generic_session_title(title: str) -> bool:
    title = (title or "").strip()
    return title in GENERIC_SESSION_TITLES or title.startswith("Bridge-")


def _session_display_title(session: dict, memories: list[dict], tags: list[str] | None = None) -> str:
    """给历史/自动导入会话生成可读标题。

    很多旧数据的 sessions.title 只是“自动同步会话”，真正可读的信息在记忆标题/摘要里。
    该函数只影响候选展示，不修改 sessions 原始标题。
    """
    title = (session.get("title") or "").strip()
    if title and not _is_generic_session_title(title):
        return title[:48]
    for m in memories:
        mt = (m.get("title") or "").strip()
        if mt and not _is_generic_session_title(mt):
            return mt[:48]
    for m in memories:
        text = (m.get("summary") or m.get("summary_detail") or m.get("raw_text") or "").strip()
        text = _compact(text, 48)
        if text:
            return text
    if tags:
        return " / ".join(tags[:3])[:48]
    return f"{session.get('agent_id') or '会话'} · {str(session.get('created_at') or '')[:10]}"


def _derive_name(session: dict, memories: list[dict], tags: list[str]) -> str:
    return _session_display_title(session, memories, tags)


def _description(memories: list[dict], tags: list[str]) -> str:
    parts = []
    if tags:
        parts.append("关键词：" + "、".join(tags[:6]))
    summaries = [_compact(m.get("summary") or m.get("summary_detail") or m.get("raw_text") or "", 80) for m in memories[:3]]
    summaries = [s for s in summaries if s]
    if summaries:
        parts.append("来源摘要：" + "；".join(summaries))
    return "\n".join(parts)


def _suggest_existing_space(name: str, tags: list[str], description: str) -> dict:
    """轻量匹配已有 Space。

    候选扫描可能一次处理几十个会话，不能在这里调用 embedding 查重，
    否则容易被 9120 启动页代理超时。这里仅做名称/别名/关键词匹配。
    """
    direct = space_manager.get_by_name(name)
    if direct:
        return {"id": direct.get("id", ""), "name": direct.get("name", ""), "reason": "same_name"}

    normalized_name = normalize_conversation(name)
    alias_row = db.fetchone(
        """SELECT s.* FROM spaces s
           JOIN space_aliases a ON a.space_id = s.id
           WHERE lower(trim(a.alias)) = ? OR a.normalized_alias = ?
           LIMIT 1""",
        ((name or "").strip().lower(), normalized_name),
    )
    if alias_row:
        data = dict(alias_row)
        return {"id": data.get("id", ""), "name": data.get("name", ""), "reason": "alias_match"}

    name_norm = normalize_conversation(" ".join([name] + tags))
    best = None
    best_score = 0.0
    for sp in space_manager.list(include_archived=False):
        tokens = [sp.get("name", ""), sp.get("description", ""), sp.get("goal", "")]
        aliases = space_manager.aliases(sp.get("id", ""))
        sp_norm = normalize_conversation(" ".join(tokens + aliases))
        if not sp_norm:
            continue
        overlap = sum(1 for t in tags if t and t in sp_norm)
        score = overlap / max(len(tags), 1)
        if name_norm and sp_norm and (name_norm in sp_norm or sp_norm in name_norm):
            score = max(score, 0.72)
        if score > best_score:
            best_score, best = score, sp
    if best and best_score >= 0.45:
        return {"id": best.get("id", ""), "name": best.get("name", ""), "reason": f"关键词/名称接近，匹配度 {best_score:.0%}"}
    return {"id": "", "name": "", "reason": ""}


def _llm_refine_candidate(name: str, description: str, tags: list[str], memories: list[dict], todos: list[dict]) -> dict:
    """用摘要轻量优化候选命名，不读取 raw_text，严格控制 token。"""
    if not llm_client.available:
        return {"name": name, "description": description, "type": "project", "method": "rule"}
    summary_lines = []
    for m in memories[:6]:
        text = _compact(m.get("summary") or m.get("summary_detail") or m.get("title") or "", 120)
        if text:
            summary_lines.append(f"- {text}")
    todo_lines = []
    for t in todos[:4]:
        title = _compact(t.get("title") or "", 60)
        if title:
            todo_lines.append(f"- {title}")
    prompt = """请根据以下【摘要信息】为一个 Memo Space Candidate 候选项目命名。
注意：你只能使用给出的摘要、标签和待办标题，不要猜测不存在的细节。
输出 JSON：{"name":"不超过24字的中文名称","type":"management|product|personal|client|dev_project|writing|general","description":"不超过80字的边界说明"}

当前规则名称：{name}
关键词：{tags}
记忆摘要：
{summaries}
待办标题：
{todos}
""".format(
        name=name,
        tags="、".join(tags[:8]),
        summaries="\n".join(summary_lines)[:900],
        todos="\n".join(todo_lines)[:260],
    )
    try:
        result = llm_client.chat_json(
            messages=[{"role": "user", "content": prompt}],
            model=getattr(config, "gating_model", None),
            temperature=0.2,
            max_tokens=240,
        )
        new_name = _compact(str(result.get("name") or name), 48)
        new_desc = _compact(str(result.get("description") or description), 180)
        new_type = str(result.get("type") or "project")
        allowed = {"management", "product", "personal", "client", "dev_project", "writing", "general", "project"}
        if new_type not in allowed:
            new_type = "project"
        return {"name": new_name or name, "description": new_desc or description, "type": new_type, "method": "llm_summary"}
    except Exception as e:
        logger.warning(f"候选项目 LLM 摘要命名失败，使用规则结果: {e}")
        return {"name": name, "description": description, "type": "project", "method": "rule_fallback"}


def _merge_suggestions(candidate_id: str, name: str, tags: list[str], limit: int = 3) -> list[dict]:
    rows = db.fetchall(
        """SELECT id, candidate_name, suggested_aliases, confidence
           FROM space_candidates
           WHERE status='pending' AND id != ?
           ORDER BY updated_at DESC
           LIMIT 120""",
        (candidate_id,),
    )
    source_terms = set(tags + [name])
    out = []
    for r in rows:
        other_terms = set(_loads(r["suggested_aliases"]) + [r["candidate_name"]])
        overlap = [t for t in source_terms if t and any(t in o or o in t for o in other_terms if o)]
        if not overlap:
            continue
        score = min(0.95, 0.55 + 0.12 * len(overlap))
        out.append({"id": r["id"], "name": r["candidate_name"], "similarity": round(score, 2), "reason": "共同线索：" + "、".join(overlap[:4])})
    return sorted(out, key=lambda x: x["similarity"], reverse=True)[:limit]


class SpaceCandidateManager:
    """候选项目扫描、查看与用户确认操作。"""

    def scan(self, limit: int = 80, min_memories: int = 1, use_llm: bool = False) -> dict:
        now = datetime.now().isoformat()
        created = 0
        updated = 0
        scanned = 0
        for session in _session_rows(limit=limit):
            memories = _session_memories(session["id"], limit=18)
            if len(memories) < min_memories:
                continue
            scanned += 1
            memory_ids = [m["id"] for m in memories]
            todos = _session_todos(session["id"])
            # 建立来源层兼容映射：不改变候选表字段含义，仍以 memo.sessions.id 作为当前 candidate source_session_ids。
            # source_sessions 作为旁路索引，给后续真实来源会话治理铺底。
            source_session_manager.ensure_from_session(session, memories=memories, todos=todos, commit=False)
            tags = _session_tags(memory_ids)
            name = _derive_name(session, memories, tags)
            desc = _description(memories, tags)
            candidate_type = "project"
            naming_method = "rule"
            if use_llm:
                refined = _llm_refine_candidate(name, desc, tags, memories, todos)
                name = refined.get("name") or name
                desc = refined.get("description") or desc
                candidate_type = refined.get("type") or "project"
                naming_method = refined.get("method") or "llm_summary"
            key = _candidate_key(name)
            aliases = _uniq([name] + tags[:6])
            confidence = min(0.92, 0.48 + len(memories) * 0.04 + len(todos) * 0.08 + len(tags) * 0.02)
            display_title = _session_display_title(session, memories, tags)
            reason = f"来自会话《{display_title}》，包含 {len(memories)} 条记忆"
            if todos:
                reason += f"、{len(todos)} 个待办"
            if tags:
                reason += "；主要线索：" + "、".join(tags[:5])
            if naming_method.startswith("llm"):
                reason += "；名称由摘要轻量优化（未读取原文）"
            existing = _suggest_existing_space(name, tags, desc)
            row = db.fetchone("SELECT * FROM space_candidates WHERE candidate_key = ?", (key,))
            if row:
                source_session_ids = _uniq(_loads(row["source_session_ids"]) + [session["id"]])
                source_memory_ids = _uniq(_loads(row["source_memory_ids"]) + memory_ids)
                source_todo_ids = _uniq(_loads(row["source_todo_ids"]) + [t["id"] for t in todos])
                suggested_aliases = _uniq(_loads(row["suggested_aliases"]) + aliases)
                db.execute(
                    """UPDATE space_candidates
                       SET description=?, confidence=max(confidence, ?), reason=?,
                           source_session_ids=?, source_memory_ids=?, source_todo_ids=?,
                           suggested_aliases=?, suggested_existing_space_id=?, suggested_existing_space_name=?,
                           updated_at=?
                       WHERE id=? AND status='pending'""",
                    (
                        desc, confidence, reason, _dumps(source_session_ids), _dumps(source_memory_ids),
                        _dumps(source_todo_ids), _dumps(suggested_aliases), existing["id"], existing["name"], now, row["id"],
                    ),
                )
                updated += db.conn.total_changes > 0
            else:
                cid = new_id()
                db.execute(
                    """INSERT INTO space_candidates
                       (id, candidate_key, candidate_name, candidate_type, description, confidence, reason, status,
                        source_session_ids, source_memory_ids, source_todo_ids, suggested_aliases,
                        suggested_existing_space_id, suggested_existing_space_name, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        cid, key, name, candidate_type, desc, confidence, reason,
                        _dumps([session["id"]]), _dumps(memory_ids), _dumps([t["id"] for t in todos]),
                        _dumps(aliases), existing["id"], existing["name"], now, now,
                    ),
                )
                self._audit(cid, "created", "", name, "system", reason)
                created += 1
        db.commit()
        self.refresh_merge_suggestions()
        remaining = self.remaining_sessions_count(min_memories=min_memories)
        return {"scanned": scanned, "created": created, "updated": updated, "pending": len(self.list(limit=1000)), "remaining_sessions": remaining}

    def remaining_sessions_count(self, min_memories: int = 1) -> int:
        row = db.fetchone(
            """SELECT COUNT(*) AS c FROM (
                   SELECT s.id, COUNT(mu.id) AS actual_memory_count
                   FROM sessions s
                   LEFT JOIN memory_units mu ON mu.session_id = s.id
                        AND COALESCE(mu.status, 'active') NOT IN ('deleted','wrong','muted')
                   WHERE s.status != 'archived'
                     AND NOT EXISTS (
                        SELECT 1 FROM space_candidates sc
                        WHERE sc.status IN ('pending','accepted','merged','merged_to_existing','ignored','rejected')
                          AND sc.source_session_ids LIKE '%' || s.id || '%'
                     )
                   GROUP BY s.id
                   HAVING actual_memory_count >= ?
               )""",
            (min_memories,),
        )
        return int(row["c"] if row else 0)

    def refresh_merge_suggestions(self) -> None:
        rows = db.fetchall("SELECT id, candidate_name, suggested_aliases FROM space_candidates WHERE status='pending'")
        for r in rows:
            tags = _loads(r["suggested_aliases"])
            suggestions = _merge_suggestions(r["id"], r["candidate_name"], tags)
            db.execute("UPDATE space_candidates SET merge_suggestions=?, updated_at=? WHERE id=?", (_dumps(suggestions), datetime.now().isoformat(), r["id"]))
        db.commit()

    def refresh_display_titles(self, limit: int = 500) -> dict:
        """刷新旧候选的来源展示名。

        只更新 space_candidates.reason 的展示文案，不修改 sessions、memory_units、权重字段。
        """
        rows = db.fetchall(
            "SELECT * FROM space_candidates WHERE status='pending' ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        )
        updated = 0
        now = datetime.now().isoformat()
        for row in rows:
            data = self._row_to_dict(row, include_sources=False)
            session_ids = data.get("source_session_ids") or []
            if not session_ids:
                continue
            sid = session_ids[0]
            session_row = db.fetchone("SELECT * FROM sessions WHERE id=?", (sid,))
            if not session_row:
                continue
            memories = _session_memories(sid, limit=18)
            todos = _session_todos(sid)
            memory_ids = [m["id"] for m in memories]
            tags = _session_tags(memory_ids)
            display_title = _session_display_title(dict(session_row), memories, tags)
            reason = f"来自会话《{display_title}》，包含 {len(memories)} 条记忆"
            if todos:
                reason += f"、{len(todos)} 个待办"
            if tags:
                reason += "；主要线索：" + "、".join(tags[:5])
            if "名称由摘要轻量优化" in (data.get("reason") or ""):
                reason += "；名称由摘要轻量优化（未读取原文）"
            if reason != data.get("reason"):
                db.execute("UPDATE space_candidates SET reason=?, updated_at=? WHERE id=?", (reason, now, data["id"]))
                self._audit(data["id"], "display_title_refreshed", data.get("reason", ""), reason, "system", "刷新自动同步会话的展示标题")
                updated += 1
        db.commit()
        return {"checked": len(rows), "updated": updated}

    def list(self, status: str = "pending", limit: int = 50) -> list[dict]:
        if status == "all":
            rows = db.fetchall("SELECT * FROM space_candidates ORDER BY updated_at DESC LIMIT ?", (limit,))
        else:
            rows = db.fetchall("SELECT * FROM space_candidates WHERE status=? ORDER BY confidence DESC, updated_at DESC LIMIT ?", (status, limit))
        return [self._row_to_dict(r, include_sources=False) for r in rows]

    def get(self, candidate_id: str) -> dict | None:
        row = db.fetchone("SELECT * FROM space_candidates WHERE id = ?", (candidate_id,))
        if not row:
            return None
        data = self._row_to_dict(row, include_sources=True)
        logs = db.fetchall("SELECT * FROM space_candidate_audit_logs WHERE candidate_id=? ORDER BY created_at DESC LIMIT 20", (candidate_id,))
        data["audit"] = [dict(r) for r in logs]
        return data

    def accept(self, candidate_id: str, name: str = "", type: str = "project", description: str = "", actor: str = "dashboard") -> dict:
        c = self.get(candidate_id)
        if not c:
            return {"error": "candidate not found"}
        if c.get("status") != "pending":
            return {"error": "candidate is not pending"}
        result = space_manager.create(
            name=(name or c["candidate_name"]).strip(),
            type=type or c.get("candidate_type") or "project",
            description=description or c.get("description", ""),
            aliases=c.get("suggested_aliases", []),
            created_by="space_candidate",
        )
        sid = result.get("id")
        if sid:
            try:
                db.execute("SAVEPOINT space_candidate_accept")
                self._bind_sources(sid, c, commit=False)
                self._decide(candidate_id, "accepted", sid, actor, f"确认为新 Space: {result.get('name', sid)}", commit=False)
                db.execute("RELEASE SAVEPOINT space_candidate_accept")
                db.commit()
            except Exception:
                db.execute("ROLLBACK TO SAVEPOINT space_candidate_accept")
                db.execute("RELEASE SAVEPOINT space_candidate_accept")
                raise
        return {**result, "candidate_id": candidate_id, "candidate_status": "accepted"}

    def merge_to_space(self, candidate_id: str, space_id: str, actor: str = "dashboard") -> dict:
        c = self.get(candidate_id)
        if not c:
            return {"error": "candidate not found"}
        if c.get("status") != "pending":
            return {"error": "candidate is not pending"}
        sp = space_manager.resolve(space_id)
        if not sp:
            return {"error": "space not found"}
        try:
            db.execute("SAVEPOINT space_candidate_merge")
            self._bind_sources(sp["id"], c, commit=False)
            self._add_alias_no_commit(sp["id"], c["candidate_name"])
            self._decide(candidate_id, "merged_to_existing", sp["id"], actor, f"合并到已有 Space: {sp['name']}", commit=False)
            db.execute("RELEASE SAVEPOINT space_candidate_merge")
            db.commit()
        except Exception:
            db.execute("ROLLBACK TO SAVEPOINT space_candidate_merge")
            db.execute("RELEASE SAVEPOINT space_candidate_merge")
            raise
        return {"ok": True, "candidate_id": candidate_id, "space_id": sp["id"], "space_name": sp["name"], "merged": True}

    def merge_many(self, candidate_ids: list[str], name: str, type: str = "project", description: str = "", actor: str = "dashboard") -> dict:
        if not (name or "").strip():
            return {"error": "missing merged space name"}
        candidates = [self.get(cid) for cid in candidate_ids]
        candidates = [c for c in candidates if c and c.get("status") == "pending"]
        if len(candidates) < 2:
            return {"error": "至少选择两个待处理候选"}
        aliases = _uniq([name] + [c.get("candidate_name", "") for c in candidates] + sum([c.get("suggested_aliases", []) for c in candidates], []))
        desc = description or "\n".join([c.get("description", "") for c in candidates[:3] if c.get("description")])
        result = space_manager.create(
            name=name.strip(),
            type=type or "project",
            description=desc,
            aliases=aliases,
            created_by="space_candidate_merge",
        )
        sid = result.get("id")
        if sid:
            try:
                db.execute("SAVEPOINT space_candidate_merge_many")
                combined = {
                    "source_memory_ids": _uniq(sum([c.get("source_memory_ids", []) for c in candidates], [])),
                    "source_todo_ids": _uniq(sum([c.get("source_todo_ids", []) for c in candidates], [])),
                    "source_session_ids": _uniq(sum([c.get("source_session_ids", []) for c in candidates], [])),
                    "confidence": max([float(c.get("confidence") or 0.7) for c in candidates] or [0.7]),
                }
                self._bind_sources(sid, combined, commit=False)
                for c in candidates:
                    self._decide(c["id"], "merged", sid, actor, f"多候选合并为新 Space: {result.get('name', sid)}", commit=False)
                db.execute("RELEASE SAVEPOINT space_candidate_merge_many")
                db.commit()
            except Exception:
                db.execute("ROLLBACK TO SAVEPOINT space_candidate_merge_many")
                db.execute("RELEASE SAVEPOINT space_candidate_merge_many")
                raise
        return {**result, "candidate_ids": [c["id"] for c in candidates], "candidate_status": "merged"}

    def ignore(self, candidate_id: str, note: str = "", actor: str = "dashboard") -> dict:
        c = self.get(candidate_id)
        if not c:
            return {"error": "candidate not found"}
        self._decide(candidate_id, "ignored", "", actor, note or "用户忽略候选项目")
        return {"ok": True, "candidate_id": candidate_id, "ignored": True}

    def _bind_sources(self, space_id: str, candidate: dict, commit: bool = True) -> None:
        now = datetime.now().isoformat()
        relevance = float(candidate.get("confidence") or 0.7)
        for mid in candidate.get("source_memory_ids", []):
            db.execute(
                """INSERT OR REPLACE INTO space_memories
                   (space_id, memory_id, relation_type, relevance, created_by, created_at)
                   VALUES (?, ?, 'candidate_confirmed', ?, 'space_candidate', ?)""",
                (space_id, mid, relevance, now),
            )
        for tid in candidate.get("source_todo_ids", []):
            db.execute(
                "UPDATE todos SET space_id=?, space_relation_type='candidate_confirmed', updated_at=? WHERE id=?",
                (space_id, now, tid),
            )
        for sid in candidate.get("source_session_ids", []):
            db.execute("UPDATE sessions SET space_id = COALESCE(space_id, ?) WHERE id = ?", (space_id, sid))
        db.execute(
            """UPDATE spaces SET
                   memory_count=(SELECT COUNT(*) FROM space_memories WHERE space_id=?),
                   todo_count=(SELECT COUNT(*) FROM todos WHERE space_id=?),
                   session_count=(SELECT COUNT(*) FROM sessions WHERE space_id=?),
                   last_active_at=?, updated_at=?
               WHERE id=?""",
            (space_id, space_id, space_id, now, now, space_id),
        )
        if commit:
            db.commit()

    def _add_alias_no_commit(self, space_id: str, alias: str) -> None:
        if not alias.strip():
            return
        db.execute(
            """INSERT OR IGNORE INTO space_aliases (id, space_id, alias, normalized_alias, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (new_id(), space_id, alias.strip(), normalize_conversation(alias), datetime.now().isoformat()),
        )

    def _decide(self, candidate_id: str, status: str, space_id: str, actor: str, note: str, commit: bool = True) -> None:
        now = datetime.now().isoformat()
        old = db.fetchone("SELECT status FROM space_candidates WHERE id=?", (candidate_id,))
        db.execute(
            """UPDATE space_candidates
               SET status=?, decided_space_id=?, decided_by=?, decided_at=?, decision_note=?, updated_at=?
               WHERE id=?""",
            (status, space_id, actor, now, note, now, candidate_id),
        )
        self._audit(candidate_id, status, old["status"] if old else "", status, actor, note)
        if commit:
            db.commit()

    def _audit(self, candidate_id: str, action: str, old_value: str, new_value: str, actor: str, note: str = "") -> None:
        db.execute(
            """INSERT INTO space_candidate_audit_logs
               (id, candidate_id, action, old_value, new_value, actor, note, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (new_id(), candidate_id, action, old_value or "", new_value or "", actor, note, datetime.now().isoformat()),
        )

    def _row_to_dict(self, row, include_sources: bool = False) -> dict:
        data = dict(row)
        for key in ["source_session_ids", "source_memory_ids", "source_todo_ids", "suggested_aliases", "merge_suggestions"]:
            data[key] = _loads(data.get(key))
        if include_sources:
            data["source_sessions"] = self._source_sessions(data["source_session_ids"])
            data["source_memories"] = self._source_memories(data["source_memory_ids"][:30])
            data["source_todos"] = self._source_todos(data["source_todo_ids"][:30])
        return data

    def _source_sessions(self, session_ids: list[str]) -> list[dict]:
        out = []
        for sid in session_ids[:12]:
            row = db.fetchone("SELECT * FROM sessions WHERE id=?", (sid,))
            if not row:
                continue
            memories = _session_memories(sid, limit=8)
            session = dict(row)
            tags = _session_tags([m["id"] for m in memories])
            out.append({
                **session,
                "display_title": _session_display_title(session, memories, tags),
                "original_title": session.get("title", ""),
                "memories": [
                    {
                        "id": m["id"],
                        "title": m.get("title", ""),
                        "summary": m.get("summary", ""),
                        "raw_text": _compact(m.get("raw_text", ""), 1200),
                        "created_at": m.get("created_at", ""),
                    }
                    for m in memories
                ],
                "todos": _session_todos(sid),
                "source_session": source_session_manager.get(sid),
            })
        return out

    def _source_memories(self, memory_ids: list[str]) -> list[dict]:
        if not memory_ids:
            return []
        placeholders = ",".join("?" for _ in memory_ids)
        rows = db.fetchall(
            f"""SELECT id, session_id, title, summary, summary_detail, raw_text, memory_type, created_at
                FROM memory_units WHERE id IN ({placeholders}) ORDER BY created_at DESC""",
            tuple(memory_ids),
        )
        return [{**dict(r), "raw_text": _compact(r["raw_text"], 1200)} for r in rows]

    def _source_todos(self, todo_ids: list[str]) -> list[dict]:
        if not todo_ids:
            return []
        placeholders = ",".join("?" for _ in todo_ids)
        rows = db.fetchall(f"SELECT * FROM todos WHERE id IN ({placeholders}) ORDER BY created_at DESC", tuple(todo_ids))
        return [dict(r) for r in rows]


space_candidate_manager = SpaceCandidateManager()
