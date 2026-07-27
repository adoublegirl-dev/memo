"""Source-aware import dry-run.

Phase E 工具：从 Agent 原始会话中构建 source-aware 导入预览报告。

当前版本只支持 --dry-run，不写 Memo 数据库，不调用 engine.init()，不执行 migration。
报告默认不保存聊天正文或真实标题正文，只保存 source_session/turn/episode/memory 的计数、
标题来源、可读性、工具日志识别情况和风险。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = PROJECT_ROOT / "reports"
MIGRATIONS_DIR = PROJECT_ROOT / "memo" / "store" / "migrations"
TEST_APPLY_CONFIRM = "TEST_APPLY"

MIN_MEMORY_TEXT_LENGTH = 30
MAX_SAMPLE_SESSIONS = 500


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def iso_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def redact_home(path: str | Path) -> str:
    text = str(path)
    try:
        home = str(Path.home())
        if text.lower().startswith(home.lower()):
            return "~" + text[len(home):]
    except Exception:
        pass
    return text


def stable_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def file_hash(path: Path, max_bytes: int = 2 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            h.update(f.read(max_bytes))
        return h.hexdigest()
    except Exception:
        return ""


def sqlite_ro_connect(path: Path) -> sqlite3.Connection:
    uri = path.resolve().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


def read_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            return None
    except Exception:
        return None


def parse_ts(text: str | None) -> float | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def jsonl_time_range(path: Path, max_lines: int = 200000) -> dict[str, Any]:
    min_ts: float | None = None
    max_ts: float | None = None
    count = 0
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i >= max_lines:
                    break
                if "timestamp" not in line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                ts = parse_ts(str(obj.get("timestamp") or obj.get("created_at") or ""))
                if ts is None:
                    continue
                count += 1
                min_ts = ts if min_ts is None else min(min_ts, ts)
                max_ts = ts if max_ts is None else max(max_ts, ts)
    except Exception:
        pass
    return {"timestamp_count": count, "start_ts": min_ts, "end_ts": max_ts}


def resolve_hana_sess_title_paths(agent_dir: Path, jsonl_files: list[Path], titles: dict[str, Any]) -> dict[str, str]:
    sess_keys = [k for k in titles if str(k).startswith("sess_")]
    summaries_dir = agent_dir / "memory" / "summaries"
    ranges = {p: jsonl_time_range(p) for p in jsonl_files}
    resolved: dict[str, str] = {}
    tolerance = 15 * 60
    for sess_id in sess_keys:
        summary_path = summaries_dir / f"{sess_id}.json"
        summary = read_json(summary_path) if summary_path.exists() else None
        if not isinstance(summary, dict):
            continue
        source_range = summary.get("source_time_range") or {}
        start = parse_ts(source_range.get("start"))
        end = parse_ts(source_range.get("end"))
        if start is None or end is None:
            continue
        candidates: list[tuple[float, Path]] = []
        for path, rng in ranges.items():
            rs = rng.get("start_ts")
            re = rng.get("end_ts")
            if rs is None or re is None:
                continue
            covers = rs - tolerance <= start and re + tolerance >= end
            overlap = max(0.0, min(end, re + tolerance) - max(start, rs - tolerance))
            if covers or overlap > 0:
                score = (end - start + 1) + overlap if covers else overlap
                candidates.append((score, path))
        candidates.sort(key=lambda x: x[0], reverse=True)
        if len(candidates) == 1 or (len(candidates) > 1 and candidates[0][0] > candidates[1][0] * 1.5):
            resolved[str(candidates[0][1])] = sess_id
            resolved[str(candidates[0][1].resolve())] = sess_id
    return resolved


@dataclass
class SourceTurnDraft:
    agent_turn_id: str = ""
    parent_turn_id: str = ""
    role: str = "unknown"
    content_hash: str = ""
    content_length: int = 0
    timestamp: str = ""
    turn_index: int = 0
    is_final_answer: bool = False
    is_tool_call: bool = False
    is_tool_result: bool = False
    tool_name: str = ""
    source_event_type: str = ""


@dataclass
class SourceSessionDraft:
    source_agent: str
    agent_session_id: str
    source_path: str
    source_hash: str
    title_source: str
    has_original_title: bool
    original_title: str = ""
    display_title: str = ""
    created_at: str = ""
    updated_at: str = ""
    turns: list[SourceTurnDraft] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)

    def estimate_episodes(self) -> int:
        user_turns = [t for t in self.turns if t.role == "user" and t.content_length >= MIN_MEMORY_TEXT_LENGTH]
        return max(len(user_turns), 1 if self.turns else 0)

    def estimate_memory_units(self) -> int:
        # 保守估算：每个有效用户问题至少可能提取 1 条长期记忆；
        # 明确工具/过程日志不计入 memory_unit。
        user_turns = [t for t in self.turns if t.role == "user" and t.content_length >= MIN_MEMORY_TEXT_LENGTH]
        assistant_final = [t for t in self.turns if t.role == "assistant" and t.is_final_answer and t.content_length >= MIN_MEMORY_TEXT_LENGTH]
        return max(len(user_turns), min(len(user_turns) + len(assistant_final), len(user_turns) * 2) if user_turns else 0)


@dataclass
class DryRunReport:
    source: str
    generated_at: str
    dry_run: bool = True
    scanned_sessions: int = 0
    importable_source_sessions: int = 0
    source_turns: int = 0
    estimated_episodes: int = 0
    estimated_memory_units: int = 0
    titled_sessions: int = 0
    missing_title_sessions: int = 0
    generated_fallback_title_sessions: int = 0
    tool_call_turns: int = 0
    tool_result_turns: int = 0
    skipped_tool_or_process_turns: int = 0
    low_value_turns: int = 0
    unreadable_sessions: int = 0
    title_sources: dict[str, int] = field(default_factory=dict)
    risks: list[str] = field(default_factory=list)
    sessions_preview: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BaseAdapter:
    name = "base"

    def list_sessions(self, limit: int = MAX_SAMPLE_SESSIONS) -> list[Path]:
        raise NotImplementedError

    def load_session(self, path: Path) -> SourceSessionDraft:
        raise NotImplementedError

    def dry_run(self, limit: int = MAX_SAMPLE_SESSIONS) -> DryRunReport:
        report = DryRunReport(source=self.name, generated_at=iso_now())
        paths = self.list_sessions(limit=limit)
        report.scanned_sessions = len(paths)
        for path in paths:
            try:
                session = self.load_session(path)
            except Exception as exc:
                report.unreadable_sessions += 1
                report.risks.append(f"读取失败 {redact_home(path)}: {exc}")
                continue
            report.importable_source_sessions += 1
            report.source_turns += len(session.turns)
            report.estimated_episodes += session.estimate_episodes()
            report.estimated_memory_units += session.estimate_memory_units()
            if session.has_original_title:
                report.titled_sessions += 1
            else:
                report.missing_title_sessions += 1
                if session.title_source == "generated_fallback":
                    report.generated_fallback_title_sessions += 1
            report.title_sources[session.title_source] = report.title_sources.get(session.title_source, 0) + 1
            report.tool_call_turns += sum(1 for t in session.turns if t.is_tool_call)
            report.tool_result_turns += sum(1 for t in session.turns if t.is_tool_result)
            report.skipped_tool_or_process_turns += sum(1 for t in session.turns if t.is_tool_call or t.is_tool_result or t.source_event_type in {"reasoning", "model_change", "thinking_level_change"})
            report.low_value_turns += sum(1 for t in session.turns if t.content_length < MIN_MEMORY_TEXT_LENGTH and not t.is_tool_call and not t.is_tool_result)
            for risk in session.risks:
                if risk not in report.risks:
                    report.risks.append(risk)
            if len(report.sessions_preview) < 12:
                report.sessions_preview.append({
                    "source_agent": session.source_agent,
                    "agent_session_id": session.agent_session_id,
                    "source_path": redact_home(session.source_path),
                    "source_hash": session.source_hash,
                    "title_source": session.title_source,
                    "has_original_title": session.has_original_title,
                    "turn_count": len(session.turns),
                    "estimated_episodes": session.estimate_episodes(),
                    "estimated_memory_units": session.estimate_memory_units(),
                    "tool_call_turns": sum(1 for t in session.turns if t.is_tool_call),
                    "tool_result_turns": sum(1 for t in session.turns if t.is_tool_result),
                    "risks": session.risks,
                })
        return report


class HanaAgentAdapter(BaseAdapter):
    name = "hanaagent"

    def __init__(self, agent_id: str = "hanako") -> None:
        self.agent_id = agent_id
        self.sessions_dir = Path.home() / ".hanako" / "agents" / agent_id / "sessions"
        self.titles_path = self.sessions_dir / "session-titles.json"
        raw_titles = read_json(self.titles_path) if self.titles_path.exists() else {}
        self.titles = raw_titles if isinstance(raw_titles, dict) else {}
        all_jsonl = sorted(self.sessions_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True) if self.sessions_dir.exists() else []
        self.sess_title_by_path = resolve_hana_sess_title_paths(self.sessions_dir.parent, all_jsonl, self.titles) if self.titles else {}

    def list_sessions(self, limit: int = MAX_SAMPLE_SESSIONS) -> list[Path]:
        if not self.sessions_dir.exists():
            return []
        return sorted(self.sessions_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]

    def _title_source_for(self, path: Path) -> tuple[str, bool, str]:
        candidates = [str(path), str(path.resolve()), path.name]
        for key in candidates:
            title = str(self.titles.get(key, "")).strip() if key in self.titles else ""
            if title:
                return "session_titles_json_path", True, title
        sess_id = self.sess_title_by_path.get(str(path)) or self.sess_title_by_path.get(str(path.resolve()))
        if sess_id:
            title = str(self.titles.get(sess_id, "")).strip()
            if title:
                return "session_titles_json_id", True, title
        return "missing", False, ""

    def load_session(self, path: Path) -> SourceSessionDraft:
        title_source, has_title, original_title = self._title_source_for(path)
        turns: list[SourceTurnDraft] = []
        risks: list[str] = []
        agent_session_id = path.stem.split("_")[-1] if "_" in path.stem else path.stem
        try:
            with path.open("r", encoding="utf-8", errors="replace") as f:
                for raw_index, line in enumerate(f):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    typ = str(obj.get("type") or "")
                    if typ == "session":
                        agent_session_id = str(obj.get("id") or agent_session_id)
                        continue
                    role = str(obj.get("message", {}).get("role") or obj.get("role") or "unknown")
                    content = obj.get("message", {}).get("content", obj.get("content", ""))
                    text, has_tool_call, has_tool_result, tool_name = normalize_content(content)
                    if typ in {"function_call", "tool_call"}:
                        has_tool_call = True
                        role = "tool"
                    if typ in {"function_call_result", "tool_result"}:
                        has_tool_result = True
                        role = "tool"
                    if role not in {"user", "assistant", "tool", "system"}:
                        role = "unknown"
                    if role == "unknown" and typ not in {"model_change", "thinking_level_change"}:
                        continue
                    turns.append(SourceTurnDraft(
                        agent_turn_id=str(obj.get("id") or ""),
                        parent_turn_id=str(obj.get("parentId") or obj.get("parent_id") or ""),
                        role=role,
                        content_hash=stable_hash(text) if text else "",
                        content_length=len(text),
                        timestamp=str(obj.get("timestamp") or ""),
                        turn_index=len(turns),
                        is_final_answer=role == "assistant" and not has_tool_call and not has_tool_result,
                        is_tool_call=has_tool_call,
                        is_tool_result=has_tool_result,
                        tool_name=tool_name,
                        source_event_type=typ,
                    ))
        except Exception as exc:
            raise RuntimeError(f"无法读取 HanaAgent JSONL: {exc}") from exc
        if not has_title:
            risks.append("HanaAgent 会话未匹配 path 标题或 sess_* summary 时间范围标题；如果只能生成 fallback，必须标记 generated_fallback。")
        return SourceSessionDraft(
            source_agent="HanaAgent",
            agent_session_id=agent_session_id,
            source_path=str(path),
            source_hash=file_hash(path),
            title_source=title_source,
            has_original_title=has_title,
            original_title=original_title,
            display_title=original_title if has_title else path.stem,
            updated_at=datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
            turns=turns,
            risks=risks,
        )


class WorkBuddyAdapter(BaseAdapter):
    name = "workbuddy"

    def __init__(self) -> None:
        self.root = Path.home() / ".workbuddy"
        self.projects_dir = self.root / "projects"
        self.db_path = self.root / "workbuddy.db"
        self.titles = self._load_titles()

    def _load_titles(self) -> dict[str, str]:
        titles: dict[str, str] = {}
        if not self.db_path.exists():
            return titles
        try:
            conn = sqlite_ro_connect(self.db_path)
            cols = {r[1] for r in conn.execute("PRAGMA table_info(sessions)").fetchall()}
            if "id" in cols and ("title" in cols or "custom_title" in cols):
                title_expr = "COALESCE(custom_title, title, '')" if "custom_title" in cols and "title" in cols else ("title" if "title" in cols else "custom_title")
                for sid, title in conn.execute(f"SELECT id, {title_expr} FROM sessions").fetchall():
                    clean_title = str(title or "").strip()
                    if clean_title:
                        titles[str(sid)] = clean_title
                        titles[str(sid).replace("-", "")] = clean_title
            conn.close()
        except Exception:
            return titles
        return titles

    def list_sessions(self, limit: int = MAX_SAMPLE_SESSIONS) -> list[Path]:
        if not self.projects_dir.exists():
            return []
        files = list(self.projects_dir.rglob("*.jsonl"))
        return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)[:limit]

    def load_session(self, path: Path) -> SourceSessionDraft:
        sid = path.stem
        normalized = sid.replace("-", "")
        original_title = self.titles.get(sid) or self.titles.get(normalized) or ""
        has_title = bool(original_title)
        turns = parse_workbuddy_jsonl(path)
        risks = [] if has_title else ["WorkBuddy JSONL 未能按文件名关联 workbuddy.db.sessions 标题。"]
        return SourceSessionDraft(
            source_agent="WorkBuddy",
            agent_session_id=sid,
            source_path=str(path),
            source_hash=file_hash(path),
            title_source="db_title" if has_title else "missing",
            has_original_title=has_title,
            original_title=original_title,
            display_title=original_title if has_title else sid,
            updated_at=datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
            turns=turns,
            risks=risks,
        )


class CodexAdapter(BaseAdapter):
    name = "codex"

    def __init__(self) -> None:
        codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
        self.roots = [codex_home / "sessions", codex_home / "archived_sessions"]

    def list_sessions(self, limit: int = MAX_SAMPLE_SESSIONS) -> list[Path]:
        files: list[Path] = []
        for root in self.roots:
            if root.exists():
                files.extend(root.rglob("*.jsonl"))
        return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)[:limit]

    def load_session(self, path: Path) -> SourceSessionDraft:
        turns = parse_generic_jsonl(path)
        return SourceSessionDraft(
            source_agent="Codex",
            agent_session_id=path.stem,
            source_path=str(path),
            source_hash=file_hash(path),
            title_source="generated_fallback",
            has_original_title=False,
            original_title="",
            display_title=path.stem,
            updated_at=datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
            turns=turns,
            risks=["Codex JSONL 未发现稳定真实 UI 标题；只能生成 fallback display_title，不能写入 original_title。"],
        )


class GenericTranscriptAdapter(BaseAdapter):
    name = "generic"

    def __init__(self, root_or_file: Path) -> None:
        self.root_or_file = root_or_file

    def list_sessions(self, limit: int = MAX_SAMPLE_SESSIONS) -> list[Path]:
        p = self.root_or_file
        if p.is_file():
            return [p]
        if not p.exists():
            return []
        files: list[Path] = []
        for pattern in ["*.jsonl", "*.md", "*.txt"]:
            files.extend(p.rglob(pattern))
        return sorted(files, key=lambda x: x.stat().st_mtime, reverse=True)[:limit]

    def load_session(self, path: Path) -> SourceSessionDraft:
        if path.suffix.lower() == ".jsonl":
            turns = parse_generic_jsonl(path)
        else:
            turns = parse_plain_text_transcript(path)
        return SourceSessionDraft(
            source_agent="GenericTranscript",
            agent_session_id=path.stem,
            source_path=str(path),
            source_hash=file_hash(path),
            title_source="file_name",
            has_original_title=False,
            original_title="",
            display_title=path.stem,
            updated_at=datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
            turns=turns,
            risks=["Generic transcript 只使用文件名/路径作为来源，无法证明真实 Agent UI 标题。"],
        )


def normalize_content(content: Any) -> tuple[str, bool, bool, str]:
    has_tool_call = False
    has_tool_result = False
    tool_name = ""
    parts: list[str] = []
    if isinstance(content, str):
        return content.strip(), False, False, ""
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict):
                typ = str(part.get("type") or "")
                if typ in {"text", "input_text", "output_text"}:
                    parts.append(str(part.get("text") or ""))
                elif typ in {"tool_use", "function_call"}:
                    has_tool_call = True
                    tool_name = str(part.get("name") or part.get("tool_name") or tool_name)
                elif typ in {"tool_result", "function_call_result"}:
                    has_tool_result = True
                    tool_name = str(part.get("name") or part.get("tool_name") or tool_name)
            elif isinstance(part, str):
                parts.append(part)
        return " ".join(p.strip() for p in parts if p.strip()).strip(), has_tool_call, has_tool_result, tool_name
    if isinstance(content, dict):
        typ = str(content.get("type") or "")
        if typ in {"tool_use", "function_call"}:
            has_tool_call = True
        if typ in {"tool_result", "function_call_result"}:
            has_tool_result = True
        tool_name = str(content.get("name") or content.get("tool_name") or "")
        text = str(content.get("text") or content.get("content") or "")
        return text.strip(), has_tool_call, has_tool_result, tool_name
    return "", False, False, ""


def parse_workbuddy_jsonl(path: Path) -> list[SourceTurnDraft]:
    turns: list[SourceTurnDraft] = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            typ = str(obj.get("type") or "")
            role = str(obj.get("role") or obj.get("message", {}).get("role") or "unknown")
            content = obj.get("content", obj.get("message", {}).get("content", ""))
            text, has_tool_call, has_tool_result, tool_name = normalize_content(content)
            if typ in {"function_call", "tool_call"}:
                has_tool_call = True
                role = "tool"
            if typ in {"function_call_result", "tool_result"}:
                has_tool_result = True
                role = "tool"
            if typ in {"reasoning", "file-history-snapshot", "custom-title", "ai-title"}:
                # 保留计数入口，但不作为 memory 主来源。
                role = "assistant" if typ == "reasoning" else "system"
            if role not in {"user", "assistant", "tool", "system"}:
                role = "unknown"
            turns.append(SourceTurnDraft(
                agent_turn_id=str(obj.get("id") or ""),
                parent_turn_id=str(obj.get("parentId") or obj.get("parent_id") or ""),
                role=role,
                content_hash=stable_hash(text) if text else "",
                content_length=len(text),
                timestamp=str(obj.get("timestamp") or obj.get("created_at") or ""),
                turn_index=len(turns),
                is_final_answer=role == "assistant" and typ == "message" and not has_tool_call and not has_tool_result,
                is_tool_call=has_tool_call,
                is_tool_result=has_tool_result,
                tool_name=tool_name,
                source_event_type=typ,
            ))
    return turns


def parse_generic_jsonl(path: Path) -> list[SourceTurnDraft]:
    turns: list[SourceTurnDraft] = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            typ = str(obj.get("type") or obj.get("event") or "")
            role = str(obj.get("role") or obj.get("message", {}).get("role") or "unknown")
            if role == "human":
                role = "user"
            content = obj.get("content", obj.get("message", {}).get("content", obj.get("text", "")))
            text, has_tool_call, has_tool_result, tool_name = normalize_content(content)
            blob = json.dumps(obj, ensure_ascii=False).lower()
            has_tool_call = has_tool_call or "tool_use" in blob or "function_call" in blob
            has_tool_result = has_tool_result or "tool_result" in blob or "function_call_result" in blob
            if has_tool_call or has_tool_result or typ in {"tool_call", "tool_result", "function_call", "function_call_result"}:
                role = "tool"
            if role not in {"user", "assistant", "tool", "system"}:
                role = "unknown"
            turns.append(SourceTurnDraft(
                agent_turn_id=str(obj.get("id") or obj.get("turn_id") or ""),
                parent_turn_id=str(obj.get("parentId") or obj.get("parent_id") or ""),
                role=role,
                content_hash=stable_hash(text) if text else "",
                content_length=len(text),
                timestamp=str(obj.get("timestamp") or obj.get("created_at") or ""),
                turn_index=len(turns),
                is_final_answer=role == "assistant" and not has_tool_call and not has_tool_result,
                is_tool_call=has_tool_call,
                is_tool_result=has_tool_result,
                tool_name=tool_name,
                source_event_type=typ,
            ))
    return turns


def parse_plain_text_transcript(path: Path) -> list[SourceTurnDraft]:
    text = path.read_text(encoding="utf-8", errors="replace")
    turns: list[SourceTurnDraft] = []
    current_role = "unknown"
    current: list[str] = []

    def flush() -> None:
        nonlocal current, current_role
        if not current:
            return
        content = "\n".join(current).strip()
        turns.append(SourceTurnDraft(
            role=current_role if current_role in {"user", "assistant", "tool", "system"} else "unknown",
            content_hash=stable_hash(content) if content else "",
            content_length=len(content),
            turn_index=len(turns),
            is_final_answer=current_role == "assistant",
            source_event_type="plain_text",
        ))
        current = []

    for line in text.splitlines():
        lower = line.strip().lower()
        if lower.startswith(("user:", "human:")):
            flush()
            current_role = "user"
            current.append(line.split(":", 1)[1].strip() if ":" in line else "")
        elif lower.startswith(("assistant:", "ai:")):
            flush()
            current_role = "assistant"
            current.append(line.split(":", 1)[1].strip() if ":" in line else "")
        elif lower.startswith("tool:"):
            flush()
            current_role = "tool"
            current.append(line.split(":", 1)[1].strip() if ":" in line else "")
        else:
            current.append(line)
    flush()
    return turns


def adapter_for(source: str, path: str = "") -> BaseAdapter:
    if source == "hanaagent":
        return HanaAgentAdapter()
    if source == "workbuddy":
        return WorkBuddyAdapter()
    if source == "codex":
        return CodexAdapter()
    if source == "generic":
        if not path:
            raise ValueError("generic source requires --path")
        return GenericTranscriptAdapter(Path(path).expanduser())
    raise ValueError(f"unknown source: {source}")


def print_human(report: DryRunReport, output: Path | None = None) -> None:
    print("=" * 72)
    print("Memo Source-aware Import Dry-run")
    print("=" * 72)
    print(f"source: {report.source}")
    print(f"generated_at: {report.generated_at}")
    print("mode: DRY-RUN（未写 Memo 数据库）")
    print(f"scanned_sessions: {report.scanned_sessions}")
    print(f"importable_source_sessions: {report.importable_source_sessions}")
    print(f"source_turns: {report.source_turns}")
    print(f"estimated_episodes: {report.estimated_episodes}")
    print(f"estimated_memory_units: {report.estimated_memory_units}")
    print(f"titled/missing/fallback: {report.titled_sessions}/{report.missing_title_sessions}/{report.generated_fallback_title_sessions}")
    print(f"tool_call/tool_result/skipped_process: {report.tool_call_turns}/{report.tool_result_turns}/{report.skipped_tool_or_process_turns}")
    print(f"low_value_turns: {report.low_value_turns}")
    print(f"title_sources: {json.dumps(report.title_sources, ensure_ascii=False)}")
    if report.risks:
        print("\nrisks:")
        for risk in report.risks[:12]:
            print(f"- {risk}")
    if output:
        print(f"\nReport written: {output}")


def run_dry_run(source: str, path: str = "", limit: int = MAX_SAMPLE_SESSIONS) -> DryRunReport:
    adapter = adapter_for(source, path=path)
    return adapter.dry_run(limit=limit)


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def apply_all_migrations(conn: sqlite3.Connection) -> int:
    latest = 0
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)")
    current_row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    current = int(current_row[0] or 0)
    for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
        version = int(migration.stem.split("_", 1)[0])
        latest = max(latest, version)
        if version <= current:
            continue
        conn.executescript(migration.read_text(encoding="utf-8"))
        conn.execute("INSERT OR IGNORE INTO schema_version(version) VALUES (?)", (version,))
    conn.commit()
    return latest


def assert_safe_test_db_path(db_path: Path) -> None:
    resolved = db_path.resolve()
    text = str(resolved).lower()
    prod_candidates = [
        (PROJECT_ROOT / "data" / "memo.db").resolve(),
    ]
    try:
        # 只读取 config，不初始化数据库。
        from memo.core.config import config

        prod_candidates.append(Path(config.db_path).resolve())
    except Exception:
        pass
    if any(resolved == p for p in prod_candidates):
        raise ValueError(f"拒绝写入生产数据库路径：{resolved}")
    if not any(token in text for token in ["test", "dev", "sandbox", "dryrun", "source_aware"]):
        raise ValueError("测试导入的 --db-path 必须包含 test/dev/sandbox/dryrun/source_aware 等安全标记。")


def insert_source_session(conn: sqlite3.Connection, session: SourceSessionDraft) -> tuple[str, str]:
    source_id = "ss_" + stable_hash(f"{session.source_agent}|{session.agent_session_id}|{session.source_path}")[:24]
    memo_session_id = "memo_" + source_id
    now = iso_now()
    conn.execute(
        """INSERT OR IGNORE INTO sessions(id, agent_id, title, status, created_at)
           VALUES (?, ?, ?, 'active', ?)""",
        (memo_session_id, session.source_agent, session.display_title or session.agent_session_id, now),
    )
    conn.execute(
        """INSERT OR REPLACE INTO source_sessions
           (id, source_type, source_agent, external_session_id, agent_session_id, source_path,
            source_hash, original_title, title_source, display_title, started_at, updated_at,
            imported_at, message_count, content_hash, status, metadata_json, created_at)
           VALUES (?, 'agent_session', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)""",
        (
            source_id,
            session.source_agent,
            session.agent_session_id,
            session.agent_session_id,
            session.source_path,
            session.source_hash,
            session.original_title if session.has_original_title else "",
            session.title_source,
            session.display_title,
            session.created_at,
            session.updated_at,
            now,
            len(session.turns),
            session.source_hash,
            json.dumps({"dry_run_apply": True, "risks": session.risks}, ensure_ascii=False),
            now,
        ),
    )
    return source_id, memo_session_id


def insert_turns(conn: sqlite3.Connection, source_id: str, session: SourceSessionDraft) -> list[str]:
    turn_ids: list[str] = []
    for turn in session.turns:
        turn_id = "turn_" + stable_hash(f"{source_id}|{turn.turn_index}|{turn.content_hash}|{turn.source_event_type}")[:24]
        turn_ids.append(turn_id)
        conn.execute(
            """INSERT OR REPLACE INTO source_turns
               (id, source_session_id, agent_turn_id, parent_turn_id, role, content, content_hash,
                timestamp, turn_index, is_final_answer, is_tool_call, is_tool_result, tool_name,
                source_event_type, metadata_json)
               VALUES (?, ?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                turn_id,
                source_id,
                turn.agent_turn_id,
                turn.parent_turn_id,
                turn.role,
                turn.content_hash,
                turn.timestamp,
                turn.turn_index,
                int(turn.is_final_answer),
                int(turn.is_tool_call),
                int(turn.is_tool_result),
                turn.tool_name,
                turn.source_event_type,
                json.dumps({"content_length": turn.content_length}, ensure_ascii=False),
            ),
        )
    return turn_ids


def insert_episode_and_memories(conn: sqlite3.Connection, source_id: str, memo_session_id: str, session: SourceSessionDraft, turn_ids: list[str]) -> tuple[int, int]:
    episode_count = 0
    memory_count = 0
    current_episode_id = ""
    for idx, turn in enumerate(session.turns):
        turn_id = turn_ids[idx]
        if turn.role == "user" and turn.content_length >= MIN_MEMORY_TEXT_LENGTH:
            episode_count += 1
            current_episode_id = "ep_" + stable_hash(f"{source_id}|{idx}|{turn.content_hash}")[:24]
            conn.execute(
                """INSERT OR REPLACE INTO episodes
                   (id, source_session_id, title, user_intent, start_turn_id, end_turn_id,
                    start_turn_index, end_turn_index, status, confidence, metadata_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ready', 0.5, ?)""",
                (
                    current_episode_id,
                    source_id,
                    f"Episode {episode_count}",
                    "dry-run-import-placeholder",
                    turn_id,
                    turn_id,
                    idx,
                    idx,
                    json.dumps({"dry_run_apply": True}, ensure_ascii=False),
                ),
            )
            conn.execute(
                """INSERT OR REPLACE INTO episode_turns(episode_id, turn_id, role_in_episode, weight)
                   VALUES (?, ?, 'trigger', 1.0)""",
                (current_episode_id, turn_id),
            )
            memory_id = "mem_" + stable_hash(f"{current_episode_id}|{turn.content_hash}")[:24]
            conn.execute(
                """INSERT OR REPLACE INTO memory_units
                   (id, session_id, title, summary, summary_detail, raw_text, memory_type,
                    source_session_id, episode_id, source_turn_start_id, source_turn_end_id,
                    memory_granularity, speaker_scope, source_confidence, is_canonical)
                   VALUES (?, ?, ?, ?, '', '', 'FACT', ?, ?, ?, ?, 'turn', 'user_claim', 0.5, 0)""",
                (
                    memory_id,
                    memo_session_id,
                    f"Dry-run memory {memory_count + 1}",
                    "Source-aware test import placeholder. Raw transcript content is not stored by this dry-run apply.",
                    source_id,
                    current_episode_id,
                    turn_id,
                    turn_id,
                ),
            )
            conn.execute(
                """INSERT OR REPLACE INTO memory_turn_sources(memory_id, turn_id, evidence_role, weight)
                   VALUES (?, ?, 'source', 1.0)""",
                (memory_id, turn_id),
            )
            conn.execute(
                """INSERT OR IGNORE INTO source_session_memories(source_session_id, memory_id, relation_type)
                   VALUES (?, ?, 'originated_from')""",
                (source_id, memory_id),
            )
            memory_count += 1
        elif current_episode_id:
            role = "final_answer" if turn.is_final_answer else ("tool_support" if turn.is_tool_call or turn.is_tool_result else "context")
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO episode_turns(episode_id, turn_id, role_in_episode, weight)
                       VALUES (?, ?, ?, 0.5)""",
                    (current_episode_id, turn_id, role),
                )
                conn.execute("UPDATE episodes SET end_turn_id=?, end_turn_index=? WHERE id=?", (turn_id, idx, current_episode_id))
            except sqlite3.IntegrityError:
                pass
    conn.execute("UPDATE sessions SET memory_count=? WHERE id=?", (memory_count, memo_session_id))
    conn.execute("UPDATE source_sessions SET memory_count=? WHERE id=?", (memory_count, source_id))
    return episode_count, memory_count


def apply_to_test_db(source: str, db_path: Path, path: str = "", limit: int = 5) -> dict[str, Any]:
    assert_safe_test_db_path(db_path)
    adapter = adapter_for(source, path=path)
    sessions = []
    for source_path in adapter.list_sessions(limit=limit):
        sessions.append(adapter.load_session(source_path))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys=ON")
    latest = apply_all_migrations(conn)
    totals = {"source_sessions": 0, "source_turns": 0, "episodes": 0, "memory_units": 0}
    for session in sessions:
        source_id, memo_session_id = insert_source_session(conn, session)
        turn_ids = insert_turns(conn, source_id, session)
        episode_count, memory_count = insert_episode_and_memories(conn, source_id, memo_session_id, session, turn_ids)
        totals["source_sessions"] += 1
        totals["source_turns"] += len(turn_ids)
        totals["episodes"] += episode_count
        totals["memory_units"] += memory_count
    conn.commit()
    validation = {
        "schema_version": conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0],
        "source_sessions": conn.execute("SELECT COUNT(*) FROM source_sessions").fetchone()[0],
        "source_turns": conn.execute("SELECT COUNT(*) FROM source_turns").fetchone()[0],
        "episodes": conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0],
        "memory_units": conn.execute("SELECT COUNT(*) FROM memory_units").fetchone()[0],
        "evidence_links": conn.execute("SELECT COUNT(*) FROM memory_turn_sources").fetchone()[0],
    }
    conn.close()
    return {
        "mode": "TEST_APPLY",
        "source": source,
        "db_path": str(db_path),
        "latest_migration": latest,
        "imported": totals,
        "validation": validation,
        "safety": "Applied only to explicit test/dev/sandbox db path; raw transcript content is not stored in memory_units/source_turns.content by this test apply.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Source-aware import dry-run. 当前版本不支持 apply。")
    parser.add_argument("--source", choices=["hanaagent", "workbuddy", "codex", "generic"], required=True)
    parser.add_argument("--path", default="", help="generic transcript 文件或目录。")
    parser.add_argument("--limit", type=int, default=MAX_SAMPLE_SESSIONS)
    parser.add_argument("--dry-run", action="store_true", help="只读预览。默认 dry-run。")
    parser.add_argument("--apply", action="store_true", help="仅允许写入显式测试库。必须传 --db-path 和 --confirm TEST_APPLY。")
    parser.add_argument("--db-path", default="", help="测试库路径。--apply 时必填，且路径必须包含 test/dev/sandbox/dryrun/source_aware。")
    parser.add_argument("--confirm", default="", help="测试库写入确认词：TEST_APPLY")
    parser.add_argument("--output", default="", help="报告输出路径；默认 reports/source-aware-import-<source>-<timestamp>.json")
    parser.add_argument("--json", action="store_true", help="控制台输出 JSON。")
    args = parser.parse_args()

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    if args.apply:
        if args.confirm != TEST_APPLY_CONFIRM:
            print("拒绝执行：测试库写入必须传入 --confirm TEST_APPLY。", file=sys.stderr)
            return 2
        if not args.db_path:
            print("拒绝执行：--apply 必须显式传入 --db-path。", file=sys.stderr)
            return 2
        try:
            result = apply_to_test_db(args.source, Path(args.db_path), path=args.path, limit=args.limit)
        except Exception as exc:
            print(f"测试库导入失败：{exc}", file=sys.stderr)
            return 1
        output = Path(args.output) if args.output else REPORTS_DIR / f"source-aware-apply-{args.source}-{now_stamp()}.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print("=" * 72)
            print("Memo Source-aware Import TEST APPLY")
            print("=" * 72)
            print(f"source: {result['source']}")
            print(f"db_path: {result['db_path']}")
            print(f"imported: {json.dumps(result['imported'], ensure_ascii=False)}")
            print(f"validation: {json.dumps(result['validation'], ensure_ascii=False)}")
            print(f"Report written: {output}")
        return 0

    report = run_dry_run(args.source, path=args.path, limit=args.limit)
    output = Path(args.output) if args.output else REPORTS_DIR / f"source-aware-import-{args.source}-{now_stamp()}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print_human(report, output=output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
