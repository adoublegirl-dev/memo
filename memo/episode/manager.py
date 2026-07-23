"""Episode Memory 管理器。

Phase 2 最小接入：
- 提供 turns → episode/canonical preview 的统一入口
- 提供 import_runs 审计记录的轻量 CRUD
- 默认不写 memory_units，不导入长期记忆，不改生产数据
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from memo.episode.canonicalizer import EpisodeCanonicalizer
from memo.episode.model import Turn
from memo.episode.splitter import EpisodeSplitter
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


class EpisodeManager:
    """Episode 预览与审计管理。"""

    def session_candidate_list(self, limit: int = 50, min_memories: int = 2, status: str = "active") -> dict:
        """按现有 sessions 聚合记忆碎片，列出需要会话层整理的候选。

        只读：不创建 episode，不改 memory_units。
        """
        limit = max(1, min(int(limit or 50), 200))
        min_memories = max(1, int(min_memories or 1))
        where_status = ""
        params: list[Any] = []
        if status and status != "all":
            where_status = "AND s.status = ?"
            params.append(status)
        rows = db.fetchall(
            f"""SELECT s.id, s.title, s.agent_id, s.status, s.created_at, s.ended_at, s.memory_count,
                       ss.id AS source_session_id, ss.source_type, ss.source_agent, ss.title AS source_title,
                       COUNT(mu.id) AS active_memory_count,
                       SUM(CASE WHEN mu.memory_type='DECISION' THEN 1 ELSE 0 END) AS decision_count,
                       SUM(CASE WHEN mu.memory_type='PREFERENCE' THEN 1 ELSE 0 END) AS preference_count,
                       SUM(CASE WHEN mu.memory_type='EVENT' THEN 1 ELSE 0 END) AS event_count,
                       SUM(CASE WHEN COALESCE(mu.canonical_kind, 'legacy')='canonical' THEN 1 ELSE 0 END) AS canonical_count,
                       SUM(CASE WHEN COALESCE(mu.status, 'active')='muted' THEN 1 ELSE 0 END) AS muted_count
                FROM sessions s
                LEFT JOIN source_sessions ss ON ss.legacy_session_id = s.id
                JOIN memory_units mu ON mu.session_id = s.id
                WHERE COALESCE(mu.status, 'active') NOT IN ('deleted','wrong') {where_status}
                GROUP BY s.id
                HAVING active_memory_count >= ?
                ORDER BY s.created_at DESC
                LIMIT ?""",
            tuple(params + [min_memories, limit]),
        )
        items = []
        for row in rows:
            data = dict(row)
            sample_memories = [dict(r) for r in db.fetchall(
                """SELECT id, title, summary, summary_detail, raw_text, memory_type, signal_level, confidence, created_at
                   FROM memory_units
                   WHERE session_id=? AND COALESCE(status, 'active') NOT IN ('deleted','wrong')
                   ORDER BY
                     CASE memory_type WHEN 'DECISION' THEN 0 WHEN 'PREFERENCE' THEN 1 WHEN 'EVENT' THEN 2 ELSE 3 END,
                     signal_level DESC, confidence DESC, created_at ASC
                   LIMIT 8""",
                (data["id"],),
            )]
            tags = self._top_tags_for_memories([m["id"] for m in sample_memories], limit=4)
            data["original_title"] = data.get("title") or ""
            data["display_title"] = self._session_display_title(data, sample_memories, tags)
            data["sample_memory_titles"] = [m.get("title", "") for m in sample_memories[:3] if m.get("title")]
            data["needs_review"] = int(data.get("canonical_count") or 0) == 0 or int(data.get("muted_count") or 0) == 0
            data["value_hint"] = self._session_value_hint(data)
            items.append(data)
        return {"items": items, "limit": limit, "min_memories": min_memories, "status": status}

    def session_candidate_get(self, session_id: str) -> dict | None:
        """查看一个会话下的碎片记忆，并生成 canonical 候选与治理建议。"""
        session = db.fetchone("SELECT * FROM sessions WHERE id=?", (session_id,))
        if not session:
            return None
        source = db.fetchone("SELECT * FROM source_sessions WHERE legacy_session_id=? OR id=?", (session_id, session_id))
        memories = [dict(r) for r in db.fetchall(
            """SELECT id, session_id, title, summary, summary_detail, raw_text, memory_type, confidence,
                      signal_level, status, user_weight, pinned, created_at,
                      COALESCE(canonical_kind, 'legacy') AS canonical_kind,
                      COALESCE(long_term_value_score, 0) AS long_term_value_score,
                      episode_id
               FROM memory_units
               WHERE session_id=? AND COALESCE(status, 'active') NOT IN ('deleted','wrong')
               ORDER BY created_at ASC""",
            (session_id,),
        )]
        if not memories:
            return {"session": dict(session), "source_session": dict(source) if source else None, "memories": [], "canonical_preview": None}

        session_data = dict(session)
        source_data = dict(source) if source else None
        tags = self._top_tags_for_memories([m["id"] for m in memories], limit=6)
        display_title = self._session_display_title({**session_data, "source_title": source_data.get("title") if source_data else ""}, memories, tags)
        preview = self._canonical_from_memory_fragments({**session_data, "display_title": display_title}, memories, source_data)
        return {
            "session": {**session_data, "display_title": display_title, "original_title": session_data.get("title", "")}, 
            "source_session": dict(source) if source else None,
            "memories": memories,
            "canonical_preview": preview,
            "dry_run": True,
        }

    def record_session_canonicalization(self, session_id: str, report: dict, mode: str = "session_preview", status: str = "dry_run") -> dict:
        """记录一次会话层整理预览审计，只写 canonicalization_runs。"""
        run_id = new_id()
        now = _now()
        memories = report.get("memories") or []
        preview = report.get("canonical_preview") or {}
        fragment_actions = preview.get("fragment_actions") or []
        superseded_count = len([x for x in fragment_actions if x.get("suggested_action") in {"mute_fragment", "supersede_by_canonical"}])
        db.execute(
            """INSERT INTO canonicalization_runs
               (id, mode, status, input_memory_count, output_memory_count, superseded_count, muted_count, report_json, created_at, completed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                mode,
                status,
                len(memories),
                1 if preview else 0,
                superseded_count,
                len([x for x in fragment_actions if x.get("suggested_action") == "mute_fragment"]),
                _dumps({"session_id": session_id, **(report or {})}),
                now,
                now,
            ),
        )
        db.commit()
        return self.canonicalization_run_get(run_id) or {"id": run_id}

    def canonicalization_run_list(self, limit: int = 50) -> list[dict]:
        limit = max(1, min(int(limit or 50), 200))
        rows = db.fetchall("SELECT * FROM canonicalization_runs ORDER BY created_at DESC LIMIT ?", (limit,))
        return [self._row_to_canonicalization_run(r, include_report=False) for r in rows]

    def canonicalization_run_get(self, run_id: str) -> dict | None:
        row = db.fetchone("SELECT * FROM canonicalization_runs WHERE id=?", (run_id,))
        return self._row_to_canonicalization_run(row, include_report=True) if row else None

    def preview_turns(
        self,
        turns: list[Turn | dict],
        source_session_id: str = "",
        agent_name: str = "",
        mode: str = "recommended",
    ) -> dict:
        """将标准 turns 预览为 canonical memory 候选。

        纯内存操作，不写数据库。
        """
        normalized = [self._coerce_turn(t, i, source_session_id, agent_name) for i, t in enumerate(turns)]
        normalized = [t for t in normalized if t is not None]
        splitter = EpisodeSplitter()
        canonicalizer = EpisodeCanonicalizer()
        episodes = splitter.split(normalized, source_session_id=source_session_id, agent_name=agent_name)
        items = []
        counts = {"recommended": 0, "manual_review": 0, "skipped": 0}
        for episode in episodes:
            draft = canonicalizer.canonicalize(episode)
            bucket = "skipped" if draft.skip else episode.status
            if bucket not in counts:
                bucket = "skipped"
            counts[bucket] += 1
            items.append({
                "episode_id": episode.id,
                "source_session_id": episode.source_session_id,
                "agent_name": episode.agent_name,
                "title": draft.title,
                "user_intent": draft.user_intent,
                "status": bucket,
                "score": draft.long_term_value_score,
                "score_reasons": episode.score_reasons,
                "skip_reasons": draft.skip_reasons,
                "memory_type": draft.suggested_memory_type,
                "feature_tags": draft.feature_tags,
                "key_facts": draft.key_facts,
                "process_summary": draft.process_summary,
                "final_conclusion": draft.final_conclusion,
                "decision_or_result": draft.decision_or_result,
                "future_impact": draft.future_impact,
                "sensitive_hints": draft.sensitive_hints,
                "source_turn_ids": draft.source_turn_ids,
                "memory_text": draft.to_memory_text(),
            })
        return {
            "dry_run": True,
            "mode": mode,
            "source_session_id": source_session_id,
            "agent_name": agent_name,
            "turn_count": len(normalized),
            "candidate_episodes": len(items),
            **counts,
            "items": items,
        }

    def record_import_run(
        self,
        report: dict,
        source_agent: str = "",
        source_path: str = "",
        mode: str = "recommended",
        status: str = "dry_run",
    ) -> dict:
        """记录一次导入/预览审计。

        只写 import_runs，不写 memory_units。用于 Dashboard 后续展示历史报告。
        调用方必须已经通过 engine._ensure_init() 进入迁移后的数据库。
        """
        run_id = new_id()
        now = _now()
        db.execute(
            """INSERT INTO import_runs
               (id, source_agent, source_path, mode, status, scanned_sessions, scanned_turns,
                candidate_episodes, imported_memories, skipped_items, report_json, created_at, completed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                source_agent or report.get("source", ""),
                source_path,
                mode or report.get("mode", "recommended"),
                status,
                int(report.get("scanned_files") or report.get("scanned_sessions") or 0),
                int(report.get("scanned_turns") or report.get("turn_count") or 0),
                int(report.get("candidate_episodes") or 0),
                int(report.get("imported_memories") or 0),
                int(report.get("skipped") or report.get("skipped_items") or 0),
                _dumps(report),
                now,
                now,
            ),
        )
        db.commit()
        return self.import_run_get(run_id) or {"id": run_id}

    def import_run_list(self, limit: int = 50, source_agent: str = "") -> list[dict]:
        limit = max(1, min(int(limit or 50), 200))
        if source_agent:
            rows = db.fetchall(
                "SELECT * FROM import_runs WHERE source_agent=? ORDER BY created_at DESC LIMIT ?",
                (source_agent, limit),
            )
        else:
            rows = db.fetchall("SELECT * FROM import_runs ORDER BY created_at DESC LIMIT ?", (limit,))
        return [self._row_to_import_run(r, include_report=False) for r in rows]

    def import_run_get(self, run_id: str) -> dict | None:
        row = db.fetchone("SELECT * FROM import_runs WHERE id=?", (run_id,))
        return self._row_to_import_run(row, include_report=True) if row else None

    def _canonical_from_memory_fragments(self, session: dict, memories: list[dict], source: dict | None = None) -> dict:
        title = session.get("display_title") or (source.get("title") if source else "")
        title = title or session.get("title") or "未命名会话"
        scored = [self._classify_fragment(m) for m in memories]
        keepers = [x for x in scored if x["suggested_action"] in {"keep_as_signal", "keep_as_evidence"}]
        process = [x for x in scored if x["suggested_action"] == "mute_fragment"]
        facts = []
        decisions = []
        tags = self._top_tags_for_memories([m["id"] for m in memories])
        for item in keepers[:8]:
            m = item["memory"]
            text = m.get("summary") or m.get("title") or m.get("summary_detail") or ""
            if not text:
                continue
            if m.get("memory_type") == "DECISION":
                decisions.append(text)
            else:
                facts.append(text)
        if not facts:
            facts = [(m.get("summary") or m.get("title") or "") for m in memories[:3] if (m.get("summary") or m.get("title"))]
        memory_type = "DECISION" if decisions else ("EVENT" if any(m.get("memory_type") == "EVENT" for m in memories) else "FACT")
        score = min(1.0, round(0.35 + min(len(keepers), 8) * 0.06 + len(decisions) * 0.08 + min(len(tags), 6) * 0.02, 3))
        fragment_actions = []
        for item in scored:
            m = item["memory"]
            fragment_actions.append({
                "memory_id": m["id"],
                "title": m.get("title") or "未命名记忆",
                "memory_type": m.get("memory_type") or "FACT",
                "status": m.get("status") or "active",
                "suggested_action": item["suggested_action"],
                "reason": item["reason"],
                "score": item["score"],
            })
        return {
            "title": f"{title}：会话级长期记忆",
            "user_intent": title,
            "key_facts": self._dedupe([x for x in facts if x])[:6],
            "decision_or_result": "；".join(self._dedupe(decisions)[:3]),
            "process_summary": f"本会话聚合了 {len(memories)} 条底层记忆碎片，其中 {len(keepers)} 条建议作为长期信号，{len(process)} 条更像过程碎片。",
            "future_impact": "建议以这条会话级 canonical memory 作为长期检索、Space、人格和图谱的主要入口；底层碎片保留为证据链。",
            "suggested_memory_type": memory_type,
            "long_term_value_score": score,
            "feature_tags": tags,
            "source_memory_ids": [m["id"] for m in memories],
            "fragment_actions": fragment_actions,
            "memory_text": "\n".join([
                f"标题：{title}：会话级长期记忆",
                f"用户意图：{title}",
                "关键事实：" + "；".join(self._dedupe([x for x in facts if x])[:6]),
                "决策 / 结果：" + "；".join(self._dedupe(decisions)[:3]),
                f"处理过程：本会话聚合了 {len(memories)} 条底层记忆碎片，其中 {len(keepers)} 条建议作为长期信号，{len(process)} 条更像过程碎片。",
            ]),
        }

    def _classify_fragment(self, memory: dict) -> dict:
        text = "\n".join(str(memory.get(k) or "") for k in ["title", "summary", "summary_detail", "raw_text"])
        memory_type = str(memory.get("memory_type") or "FACT")
        pinned = bool(memory.get("pinned"))
        signal = int(memory.get("signal_level") or 0)
        score = 0.35
        reasons = []
        if memory_type in {"DECISION", "PREFERENCE"}:
            score += 0.30; reasons.append("决策/偏好类记忆，适合作为长期信号")
        elif memory_type == "EVENT":
            score += 0.18; reasons.append("事件类记忆，可作为会话结论证据")
        if pinned or signal >= 2:
            score += 0.18; reasons.append("用户显式或高信号记忆")
        if any(word in text for word in ["最终", "结论", "完成", "已发布", "根因", "修复", "决定", "必须", "不要"]):
            score += 0.16; reasons.append("包含结论/结果/约束")
        if any(word in text for word in ["正在", "准备", "我先", "调用", "Loading", "snapshot", "命令输出", "等待", "重试"]):
            score -= 0.22; reasons.append("偏过程碎片")
        score = max(0.0, min(1.0, round(score, 3)))
        if score >= 0.72:
            action = "keep_as_signal"
        elif score >= 0.45:
            action = "keep_as_evidence"
        else:
            action = "mute_fragment"
        return {"memory": memory, "suggested_action": action, "reason": "；".join(reasons) or "信息量一般，建议作为证据链评估", "score": score}

    def _top_tags_for_memories(self, memory_ids: list[str], limit: int = 10) -> list[str]:
        if not memory_ids:
            return []
        placeholders = ",".join("?" * len(memory_ids))
        rows = db.fetchall(
            f"""SELECT ft.name, COUNT(*) AS c
                FROM tag_mentions tm
                JOIN feature_tags ft ON ft.id = tm.tag_id
                WHERE tm.memory_unit_id IN ({placeholders})
                GROUP BY ft.id
                ORDER BY c DESC, ft.retrieval_strength DESC
                LIMIT ?""",
            tuple(memory_ids + [limit]),
        )
        return [r["name"] for r in rows]

    def _compact(self, text: str, limit: int = 48) -> str:
        import re
        text = re.sub(r"\s+", " ", (text or "").strip())
        return text[:limit] + ("…" if len(text) > limit else "")

    def _is_generic_session_title(self, title: str) -> bool:
        title = (title or "").strip()
        return title in {"", "自动会话", "自动同步会话", "自动导入会话", "未命名会话", "新会话"} or title.startswith("Bridge-")

    def _session_display_title(self, session: dict, memories: list[dict], tags: list[str] | None = None) -> str:
        """为自动同步/旧会话生成可读展示名，不修改 sessions 原始标题。"""
        source_title = (session.get("source_title") or "").strip()
        if source_title and not self._is_generic_session_title(source_title):
            return source_title[:56]
        title = (session.get("title") or "").strip()
        if title and not self._is_generic_session_title(title):
            return title[:56]
        # 优先使用决策/事件/高信号记忆标题。
        ordered = sorted(
            memories,
            key=lambda m: (
                0 if m.get("memory_type") == "DECISION" else 1 if m.get("memory_type") == "PREFERENCE" else 2 if m.get("memory_type") == "EVENT" else 3,
                -int(m.get("signal_level") or 0),
                -float(m.get("confidence") or 0),
            ),
        )
        for m in ordered:
            mt = (m.get("title") or "").strip()
            if mt and not self._is_generic_session_title(mt):
                return mt[:56]
        for m in ordered:
            text = self._compact(m.get("summary") or m.get("summary_detail") or m.get("raw_text") or "", 56)
            if text:
                return text
        if tags:
            return " / ".join(tags[:3])[:56]
        return f"{session.get('agent_id') or '会话'} · {str(session.get('created_at') or '')[:10]}"

    def _session_value_hint(self, data: dict) -> str:
        if int(data.get("decision_count") or 0) > 0:
            return "包含决策，建议优先整理"
        if int(data.get("preference_count") or 0) > 0:
            return "包含偏好，建议进入人工确认"
        if int(data.get("event_count") or 0) > 0:
            return "包含事件进展，可整理为会话结论"
        return "普通事实会话，适合抽样检查"

    def _row_to_canonicalization_run(self, row, include_report: bool = False) -> dict:
        data = dict(row)
        report = _loads(data.pop("report_json", "{}"))
        data["session_id"] = report.get("session_id", "")
        data["canonical_title"] = (report.get("canonical_preview") or {}).get("title", "")
        if include_report:
            data["report"] = report
        return data

    def _dedupe(self, items: list[str]) -> list[str]:
        seen = set(); result = []
        for item in items:
            item = str(item or "").strip()
            if item and item not in seen:
                seen.add(item); result.append(item)
        return result

    def _row_to_import_run(self, row, include_report: bool = False) -> dict:
        data = dict(row)
        report = _loads(data.pop("report_json", "{}"))
        data["summary"] = {
            "recommended": report.get("recommended", 0),
            "manual_review": report.get("manual_review", 0),
            "skipped": report.get("skipped", data.get("skipped_items", 0)),
        }
        if include_report:
            data["report"] = report
        return data

    def _coerce_turn(self, value: Turn | dict, index: int, source_session_id: str, agent_name: str) -> Turn | None:
        if isinstance(value, Turn):
            return value
        if not isinstance(value, dict):
            return None
        role = str(value.get("role") or "").lower()
        content = value.get("content") or ""
        if isinstance(content, list):
            content = "\n".join(str(x) for x in content)
        content = str(content).strip()
        if role not in {"user", "assistant", "tool", "system"} or not content:
            return None
        session_id = str(value.get("session_id") or source_session_id or "preview")
        return Turn(
            agent=str(value.get("agent") or agent_name or "generic"),
            session_id=session_id,
            turn_id=str(value.get("turn_id") or value.get("id") or f"{session_id}:{index}"),
            role=role,
            content=content,
            timestamp=str(value.get("timestamp") or value.get("created_at") or ""),
            tool_name=str(value.get("tool_name") or ""),
            is_final=bool(value.get("is_final") or value.get("final") or False),
            metadata=value.get("metadata") if isinstance(value.get("metadata"), dict) else {},
        )


episode_manager = EpisodeManager()
