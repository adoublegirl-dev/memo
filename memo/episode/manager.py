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
