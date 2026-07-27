"""只读探测 Agent 会话来源结构。

Phase B 工具：扫描本机 HanaAgent / WorkBuddy / Qoder / Codex / Generic transcript
候选路径，判断是否能读取真实会话标题、turn、工具调用等来源信息。

安全原则：
- 不导入 Memo 数据库。
- 不写入任何 Agent 原始目录。
- 报告默认不保存聊天正文或标题正文，只保存计数、路径、结构、风险。
- SQLite 使用只读 mode=ro 连接。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sqlite3
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = PROJECT_ROOT / "reports"

TEXT_EXTS = {".jsonl", ".json", ".md", ".txt", ".log"}
DB_EXTS = {".db", ".sqlite", ".sqlite3"}

TRUSTED_SOURCE_NOTES = [
    {
        "topic": "Codex CLI local sessions",
        "summary": "Codex CLI / VS Code extension sessions are commonly stored as JSONL rollout files under ~/.codex/sessions/YYYY/MM/DD/ or $CODEX_HOME/sessions/.",
        "urls": [
            "https://github.com/openai/codex/discussions/2956",
            "https://www.verdent.ai/guides/codex-cli-resume-continue-save-chat",
        ],
    },
    {
        "topic": "Claude Code local sessions as reference pattern",
        "summary": "Claude Code is reported to store local transcripts as JSONL under ~/.claude/projects/, useful for GenericTranscriptAdapter path design.",
        "urls": ["https://fazm.ai/blog/claude-code-previous-sessions-jsonl-transcripts"],
    },
    {
        "topic": "Qoder public docs",
        "summary": "Public Qoder pages describe product capabilities and memory/extensions, but did not provide a stable local transcript path in the searched sources. Local probing is authoritative.",
        "urls": ["https://qoder.com/ide", "https://qoder.com/zh/ide"],
    },
]


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


def sha256_file(path: Path, max_bytes: int = 2 * 1024 * 1024) -> str:
    """对候选文件头部做摘要，用于结构识别，不读取全量大文件。"""
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            h.update(f.read(max_bytes))
        return h.hexdigest()
    except Exception:
        return ""


def safe_stat(path: Path) -> dict[str, Any]:
    try:
        st = path.stat()
        return {
            "path": redact_home(path),
            "exists": True,
            "size": st.st_size,
            "mtime": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
        }
    except Exception as exc:
        return {"path": redact_home(path), "exists": False, "error": str(exc)}


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
        normalized = str(text).replace("Z", "+00:00")
        return datetime.fromisoformat(normalized).timestamp()
    except Exception:
        return None


def jsonl_time_range(path: Path, max_lines: int = 200000) -> dict[str, Any]:
    """统计 JSONL timestamp 范围，不保存正文。"""
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
    except Exception as exc:
        return {"path": redact_home(path), "error": str(exc), "timestamp_count": 0}
    return {
        "path": redact_home(path),
        "timestamp_count": count,
        "start_ts": min_ts,
        "end_ts": max_ts,
        "start": datetime.fromtimestamp(min_ts, timezone.utc).isoformat() if min_ts is not None else "",
        "end": datetime.fromtimestamp(max_ts, timezone.utc).isoformat() if max_ts is not None else "",
    }


def resolve_hana_sess_titles(agent_dir: Path, jsonl_files: list[Path], titles: dict[str, Any]) -> dict[str, Any]:
    """用 memory/summaries/sess_*.json 的 source_time_range 保守映射到 JSONL。

    只在唯一最高候选时认定 resolved；不保存标题正文。
    """
    sess_keys = [k for k in titles if str(k).startswith("sess_")]
    summaries_dir = agent_dir / "memory" / "summaries"
    ranges = {p: jsonl_time_range(p) for p in jsonl_files}
    resolved: dict[str, str] = {}
    unresolved = 0
    ambiguous = 0
    missing_summary = 0
    examples: list[dict[str, Any]] = []
    tolerance = 15 * 60
    for sess_id in sess_keys:
        summary_path = summaries_dir / f"{sess_id}.json"
        summary = read_json(summary_path) if summary_path.exists() else None
        if not isinstance(summary, dict):
            missing_summary += 1
            continue
        source_range = summary.get("source_time_range") or {}
        start = parse_ts(source_range.get("start"))
        end = parse_ts(source_range.get("end"))
        if start is None or end is None:
            unresolved += 1
            continue
        candidates: list[tuple[float, Path]] = []
        for path, rng in ranges.items():
            rs = rng.get("start_ts")
            re = rng.get("end_ts")
            if rs is None or re is None:
                continue
            # 覆盖或重叠均可作为候选，覆盖优先。
            covers = rs - tolerance <= start and re + tolerance >= end
            overlap = max(0.0, min(end, re + tolerance) - max(start, rs - tolerance))
            if covers or overlap > 0:
                score = (end - start + 1) + overlap if covers else overlap
                candidates.append((score, path))
        candidates.sort(key=lambda x: x[0], reverse=True)
        if len(candidates) == 1 or (len(candidates) > 1 and candidates[0][0] > candidates[1][0] * 1.5):
            resolved[sess_id] = str(candidates[0][1])
            if len(examples) < 8:
                examples.append({
                    "sess_id": sess_id,
                    "jsonl_path": redact_home(candidates[0][1]),
                    "confidence": "time_range_unique" if len(candidates) == 1 else "time_range_best",
                    "source_time_range": {"start": source_range.get("start", ""), "end": source_range.get("end", "")},
                })
        elif candidates:
            ambiguous += 1
        else:
            unresolved += 1
    path_to_sess: dict[str, list[str]] = {}
    for sess_id, path in resolved.items():
        path_to_sess.setdefault(path, []).append(sess_id)
    unique_path_to_sess = {path: ids[0] for path, ids in path_to_sess.items() if len(ids) == 1}
    return {
        "sess_title_keys": len(sess_keys),
        "summary_files_found": len(sess_keys) - missing_summary,
        "resolved_sess_to_jsonl": len(resolved),
        "unique_jsonl_matches": len(unique_path_to_sess),
        "ambiguous": ambiguous,
        "unresolved": unresolved,
        "missing_summary": missing_summary,
        "path_to_sess": unique_path_to_sess,
        "examples": examples,
    }


def inspect_jsonl(path: Path, max_lines: int = 2000) -> dict[str, Any]:
    """只统计 JSONL 结构，不保存正文。"""
    result: dict[str, Any] = {
        "path": redact_home(path),
        "readable": False,
        "plaintext": False,
        "valid_json_lines": 0,
        "invalid_json_lines": 0,
        "type_counts": {},
        "role_counts": {},
        "has_tool_call": False,
        "has_tool_result": False,
        "has_session_header": False,
        "session_id_present": False,
        "timestamp_present": False,
        "content_fields_present": False,
    }
    type_counts: Counter[str] = Counter()
    role_counts: Counter[str] = Counter()
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i >= max_lines:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    result["invalid_json_lines"] += 1
                    continue
                result["valid_json_lines"] += 1
                result["plaintext"] = True
                typ = str(obj.get("type") or obj.get("event") or obj.get("kind") or "")
                if typ:
                    type_counts[typ] += 1
                role = str(obj.get("role") or obj.get("message", {}).get("role") or "")
                if role:
                    role_counts[role] += 1
                if typ == "session" or "session" in obj:
                    result["has_session_header"] = True
                if obj.get("id") or obj.get("session_id") or obj.get("conversation_id"):
                    result["session_id_present"] = True
                if obj.get("timestamp") or obj.get("created_at") or obj.get("time"):
                    result["timestamp_present"] = True
                if "content" in obj or "message" in obj or "text" in obj:
                    result["content_fields_present"] = True
                text_blob = json.dumps(obj, ensure_ascii=False).lower()
                if "tool_use" in text_blob or "function_call" in text_blob or typ in {"tool_call", "function_call"}:
                    result["has_tool_call"] = True
                if "tool_result" in text_blob or "function_call_result" in text_blob or typ in {"tool_result", "function_call_result"}:
                    result["has_tool_result"] = True
        result["readable"] = result["valid_json_lines"] > 0
        result["type_counts"] = dict(type_counts.most_common(20))
        result["role_counts"] = dict(role_counts.most_common(20))
    except Exception as exc:
        result["error"] = str(exc)
    return result


def sqlite_ro_connect(path: Path) -> sqlite3.Connection:
    uri = path.resolve().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


def inspect_sqlite(path: Path, sample_rows: bool = False) -> dict[str, Any]:
    """只读 SQLite 结构。默认不保存行数据。"""
    result: dict[str, Any] = {
        "path": redact_home(path),
        "readable": False,
        "plaintext_or_sqlite": False,
        "tables": [],
        "session_like_tables": [],
        "message_like_tables": [],
        "title_like_columns": [],
    }
    try:
        conn = sqlite_ro_connect(path)
        conn.row_factory = sqlite3.Row
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
        result["readable"] = True
        result["plaintext_or_sqlite"] = True
        result["tables"] = tables[:80]
        table_infos: dict[str, list[str]] = {}
        for table in tables[:80]:
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({quote_ident(table)})").fetchall()]
            table_infos[table] = cols
            lname = table.lower()
            if any(k in lname for k in ["session", "conversation", "chat", "thread"]):
                result["session_like_tables"].append({"table": table, "columns": cols})
            if any(k in lname for k in ["message", "turn", "event", "log"]):
                result["message_like_tables"].append({"table": table, "columns": cols})
            for col in cols:
                if any(k in col.lower() for k in ["title", "name", "subject"]):
                    result["title_like_columns"].append({"table": table, "column": col})
        conn.close()
    except Exception as exc:
        result["error"] = str(exc)
    return result


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def count_sqlite_column(path: Path, table: str, column: str) -> int | None:
    try:
        conn = sqlite_ro_connect(path)
        row = conn.execute(
            f"SELECT COUNT(*) FROM {quote_ident(table)} WHERE {quote_ident(column)} IS NOT NULL AND TRIM(CAST({quote_ident(column)} AS TEXT)) <> ''"
        ).fetchone()
        conn.close()
        return int(row[0] if row else 0)
    except Exception:
        return None


def safe_glob(root: Path, patterns: list[str], max_files: int = 500) -> list[Path]:
    files: list[Path] = []
    if not root.exists():
        return files
    for pattern in patterns:
        try:
            for p in root.rglob(pattern):
                if p.is_file():
                    files.append(p)
                    if len(files) >= max_files:
                        return files
        except Exception:
            continue
    return files


@dataclass
class AgentDetectReport:
    agent: str
    detected: bool = False
    roots_checked: list[str] = field(default_factory=list)
    session_count: int = 0
    title_count: int = 0
    missing_title_count: int = 0
    title_sources: list[str] = field(default_factory=list)
    turn_sources: list[str] = field(default_factory=list)
    tool_call_recognizable: str = "unknown"
    created_updated_available: str = "unknown"
    readability: str = "unknown"
    encryption_or_locking: str = "unknown"
    structures: dict[str, Any] = field(default_factory=dict)
    risks: list[str] = field(default_factory=list)
    next_checks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "detected": self.detected,
            "roots_checked": self.roots_checked,
            "session_count": self.session_count,
            "title_count": self.title_count,
            "missing_title_count": self.missing_title_count,
            "title_sources": self.title_sources,
            "turn_sources": self.turn_sources,
            "tool_call_recognizable": self.tool_call_recognizable,
            "created_updated_available": self.created_updated_available,
            "readability": self.readability,
            "encryption_or_locking": self.encryption_or_locking,
            "structures": self.structures,
            "risks": self.risks,
            "next_checks": self.next_checks,
        }


class Detector:
    def __init__(self) -> None:
        self.home = Path.home()
        self.appdata = Path(os.environ.get("APPDATA", self.home / "AppData" / "Roaming"))
        self.localappdata = Path(os.environ.get("LOCALAPPDATA", self.home / "AppData" / "Local"))

    def detect_hanaagent(self) -> AgentDetectReport:
        report = AgentDetectReport(agent="HanaAgent")
        agents_root = self.home / ".hanako" / "agents"
        report.roots_checked.append(redact_home(agents_root))
        agent_dirs = [agents_root / "hanako"]
        if agents_root.exists():
            for p in agents_root.iterdir():
                if p.is_dir() and (p / "sessions").exists() and p not in agent_dirs:
                    agent_dirs.append(p)
        total_sessions = 0
        total_titles = 0
        structures: dict[str, Any] = {"agents": []}
        any_jsonl_readable = False
        any_tool = False
        for agent_dir in agent_dirs:
            sessions_dir = agent_dir / "sessions"
            titles_path = sessions_dir / "session-titles.json"
            meta_path = sessions_dir / "session-meta.json"
            manifest_path = sessions_dir / "session-manifest.db"
            jsonl_files = sorted(sessions_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True) if sessions_dir.exists() else []
            titles = read_json(titles_path) if titles_path.exists() else {}
            titles = titles if isinstance(titles, dict) else {}
            title_keys = set(titles.keys())
            sess_resolution = resolve_hana_sess_titles(agent_dir, jsonl_files, titles) if title_keys else {"path_to_sess": {}}
            sess_path_map = sess_resolution.get("path_to_sess", {}) if isinstance(sess_resolution, dict) else {}
            title_key_shapes = {
                "path_like": sum(1 for k in title_keys if "\\" in k or "/" in k),
                "sess_id_like": sum(1 for k in title_keys if k.startswith("sess_")),
                "file_name_like": sum(1 for k in title_keys if k.endswith(".jsonl") and ("\\" not in k and "/" not in k)),
                "other": 0,
            }
            title_key_shapes["other"] = max(len(title_keys) - sum(title_key_shapes.values()), 0)
            path_titled = 0
            sess_titled = 0
            for jf in jsonl_files:
                if str(jf) in title_keys or str(jf.resolve()) in title_keys or redact_home(jf) in title_keys or jf.name in title_keys:
                    path_titled += 1
                elif str(jf) in sess_path_map or str(jf.resolve()) in sess_path_map:
                    sess_titled += 1
            titled = path_titled + sess_titled
            total_sessions += len(jsonl_files)
            total_titles += titled
            sample_inspections = [inspect_jsonl(p, max_lines=500) for p in jsonl_files[:3]]
            any_jsonl_readable = any_jsonl_readable or any(s.get("readable") for s in sample_inspections)
            any_tool = any_tool or any(s.get("has_tool_call") or s.get("has_tool_result") for s in sample_inspections)
            agent_struct = {
                "agent_dir": redact_home(agent_dir),
                "sessions_dir": safe_stat(sessions_dir),
                "jsonl_session_files": len(jsonl_files),
                "session_titles_json": safe_stat(titles_path),
                "session_titles_entries": len(titles) if isinstance(titles, dict) else 0,
                "session_title_key_shapes": title_key_shapes,
                "matched_titles_by_path": path_titled,
                "matched_titles_by_sess_time_range": sess_titled,
                "sess_title_resolution": {k: v for k, v in sess_resolution.items() if k != "path_to_sess"},
                "session_meta_json": safe_stat(meta_path),
                "session_manifest_db": safe_stat(manifest_path),
                "sample_jsonl_structure": sample_inspections,
            }
            if manifest_path.exists():
                agent_struct["manifest_db_structure"] = inspect_sqlite(manifest_path)
            structures["agents"].append(agent_struct)
        report.detected = total_sessions > 0
        report.session_count = total_sessions
        report.title_count = total_titles
        report.missing_title_count = max(total_sessions - total_titles, 0)
        if total_titles:
            report.title_sources.append("session-titles.json[path]")
        if any(
            agent.get("matched_titles_by_sess_time_range", 0) > 0
            for agent in structures.get("agents", [])
        ):
            report.title_sources.append("session-titles.json[sess_*] + memory/summaries source_time_range")
        if any((self.home / ".hanako" / "agents" / "hanako" / "sessions" / "session-manifest.db").exists() for _ in [0]):
            report.title_sources.append("session-manifest.db")
        report.turn_sources.append("~/.hanako/agents/<agent_id>/sessions/*.jsonl")
        report.tool_call_recognizable = "yes" if any_tool else "partial_or_not_seen_in_samples"
        report.created_updated_available = "jsonl session header timestamp + file mtime"
        report.readability = "plaintext_jsonl" if any_jsonl_readable else "not_readable_or_empty"
        report.encryption_or_locking = "no_encryption_detected" if any_jsonl_readable else "unknown"
        report.structures = structures
        if report.missing_title_count:
            report.risks.append("部分 HanaAgent JSONL 仍未匹配真实标题；sess_* 仅在 memory/summaries source_time_range 能唯一映射到 JSONL 时才可作为真实会话标题来源。")
        report.risks.append("不要用 Memo 生成标题写入 original_title；只能作为 display_title fallback。")
        report.next_checks.append("实现 HanaAgentAdapter：优先 path 标题，其次使用 sess_* summary 时间范围唯一映射标题。")
        return report

    def detect_workbuddy(self) -> AgentDetectReport:
        report = AgentDetectReport(agent="WorkBuddy")
        root = self.home / ".workbuddy"
        projects = root / "projects"
        db_path = root / "workbuddy.db"
        report.roots_checked.extend([redact_home(root), redact_home(projects), redact_home(db_path)])
        jsonl_files = safe_glob(projects, ["*.jsonl"], max_files=2000)
        structures: dict[str, Any] = {
            "root": safe_stat(root),
            "projects_dir": safe_stat(projects),
            "workbuddy_db": safe_stat(db_path),
            "jsonl_session_files": len(jsonl_files),
            "sample_jsonl_structure": [inspect_jsonl(p, max_lines=500) for p in jsonl_files[:3]],
        }
        db_readable = False
        title_count = 0
        db_session_count = 0
        exact_matches = 0
        normalized_matches = 0
        if db_path.exists():
            db_struct = inspect_sqlite(db_path)
            structures["workbuddy_db_structure"] = db_struct
            db_readable = bool(db_struct.get("readable"))
            try:
                conn = sqlite_ro_connect(db_path)
                session_cols = [r[1] for r in conn.execute("PRAGMA table_info(sessions)").fetchall()]
                if "id" in session_cols:
                    rows = conn.execute("SELECT id, title, custom_title FROM sessions").fetchall() if {"title", "custom_title"}.issubset(set(session_cols)) else []
                    db_session_count = len(rows)
                    title_count = sum(1 for r in rows if (r[1] or r[2]))
                    db_ids = {str(r[0]) for r in rows}
                    normalized_ids = {str(r[0]).replace("-", "") for r in rows}
                    for jf in jsonl_files:
                        stem = jf.stem
                        if stem in db_ids:
                            exact_matches += 1
                        if stem.replace("-", "") in normalized_ids:
                            normalized_matches += 1
                conn.close()
            except Exception as exc:
                structures["workbuddy_db_query_error"] = str(exc)
        report.detected = root.exists() or bool(jsonl_files) or db_path.exists()
        report.session_count = max(len(jsonl_files), db_session_count)
        report.title_count = title_count
        report.missing_title_count = max(report.session_count - title_count, 0) if report.session_count else 0
        report.title_sources = ["~/.workbuddy/workbuddy.db.sessions.custom_title/title"] if title_count else []
        report.turn_sources = ["~/.workbuddy/projects/**/*.jsonl"] if jsonl_files else []
        report.tool_call_recognizable = "yes_or_partial" if any(s.get("has_tool_call") or s.get("has_tool_result") for s in structures["sample_jsonl_structure"]) else "partial_or_not_seen_in_samples"
        report.created_updated_available = "workbuddy.db sessions.created_at/updated_at + jsonl file mtime" if db_readable else "jsonl file mtime only"
        report.readability = "sqlite_and_plaintext_jsonl" if db_readable and jsonl_files else ("sqlite_only" if db_readable else "unknown")
        report.encryption_or_locking = "no_encryption_detected" if db_readable or jsonl_files else "unknown"
        structures["db_jsonl_id_matches"] = {"exact": exact_matches, "normalized_without_hyphen": normalized_matches}
        report.structures = structures
        if db_readable and jsonl_files and normalized_matches < len(jsonl_files):
            report.risks.append("WorkBuddy JSONL 文件名与 workbuddy.db.sessions.id 未完全匹配，需要进一步确认当前版本身份关联规则。")
        report.next_checks.append("实现 WorkBuddyAdapter：优先按 normalized session id 关联 DB 标题与 JSONL turn。")
        return report

    def detect_qoder(self) -> AgentDetectReport:
        report = AgentDetectReport(agent="Qoder/QoderWork")
        roots = [
            self.home / ".qoder",
            self.home / ".qoderwork",
            self.appdata / "Qoder",
            self.localappdata / "Qoder",
            self.appdata / "QoderWork",
            self.localappdata / "QoderWork",
        ]
        report.roots_checked = [redact_home(p) for p in roots]
        structures: dict[str, Any] = {"roots": []}
        candidate_files: list[Path] = []
        for root in roots:
            root_info = {"root": safe_stat(root), "candidate_files": []}
            if root.exists():
                files = []
                # 避免把 VSCode 扩展目录全部当作会话。
                targeted_dirs = [root / "agents", root / "sessions", root / "logs", root / "User", root / "workspaceStorage"]
                for td in targeted_dirs:
                    files.extend(safe_glob(td, ["*.jsonl", "*.db", "*.sqlite", "*.sqlite3", "*.json"], max_files=300))
                # 根目录少量配置也记录，但不读取扩展包内容。
                for p in root.glob("*.db"):
                    files.append(p)
                for p in root.glob("*.jsonl"):
                    files.append(p)
                unique = []
                seen = set()
                for p in files:
                    if p not in seen:
                        unique.append(p)
                        seen.add(p)
                candidate_files.extend(unique)
                for p in unique[:50]:
                    item = safe_stat(p)
                    if p.suffix.lower() == ".jsonl":
                        item["jsonl_structure"] = inspect_jsonl(p, max_lines=300)
                    elif p.suffix.lower() in DB_EXTS:
                        item["sqlite_structure"] = inspect_sqlite(p)
                    root_info["candidate_files"].append(item)
            structures["roots"].append(root_info)
        jsonl_files = [p for p in candidate_files if p.suffix.lower() == ".jsonl"]
        db_files = [p for p in candidate_files if p.suffix.lower() in DB_EXTS]
        report.detected = any(p.exists() for p in roots)
        report.session_count = len(jsonl_files)
        report.title_count = 0
        report.missing_title_count = len(jsonl_files)
        report.turn_sources = ["local candidate *.jsonl under Qoder roots"] if jsonl_files else []
        report.title_sources = []
        report.tool_call_recognizable = "unknown"
        report.created_updated_available = "file mtime only unless DB schema proves otherwise"
        report.readability = "candidate_jsonl_or_sqlite" if (jsonl_files or db_files) else "no_session_store_detected"
        report.encryption_or_locking = "no_encryption_detected_in_candidates" if (jsonl_files or db_files) else "not_enough_evidence"
        report.structures = structures
        if not jsonl_files and not db_files:
            report.risks.append("本机 Qoder 目录存在但未发现明确会话 JSONL/SQLite；可能版本未产生会话、路径偏离、或存储在应用私有目录。")
        report.risks.append("公开 Qoder 页面未提供稳定本地 transcript 路径，后续需以本机版本探测和用户指定路径为准。")
        report.next_checks.append("打开/使用 Qoder 产生一条测试会话后复跑探测，观察新增文件。")
        return report

    def detect_codex(self) -> AgentDetectReport:
        report = AgentDetectReport(agent="Codex")
        codex_home = Path(os.environ.get("CODEX_HOME", self.home / ".codex"))
        roots = [
            codex_home / "sessions",
            codex_home / "archived_sessions",
            self.appdata / "Codex",
            self.localappdata / "Codex",
        ]
        report.roots_checked = [redact_home(p) for p in roots]
        structures: dict[str, Any] = {"roots": []}
        jsonl_files: list[Path] = []
        for root in roots:
            root_info = {"root": safe_stat(root), "jsonl_files": 0, "sample_jsonl_structure": []}
            if root.exists():
                files = safe_glob(root, ["*.jsonl"], max_files=1000)
                jsonl_files.extend(files)
                root_info["jsonl_files"] = len(files)
                root_info["sample_jsonl_structure"] = [inspect_jsonl(p, max_lines=500) for p in files[:3]]
            structures["roots"].append(root_info)
        any_readable = any(s.get("readable") for r in structures["roots"] for s in r.get("sample_jsonl_structure", []))
        any_tool = any((s.get("has_tool_call") or s.get("has_tool_result")) for r in structures["roots"] for s in r.get("sample_jsonl_structure", []))
        report.detected = any(p.exists() for p in roots)
        report.session_count = len(jsonl_files)
        report.title_count = 0
        report.missing_title_count = len(jsonl_files)
        report.title_sources = []
        report.turn_sources = ["$CODEX_HOME/sessions/**/*.jsonl", "$CODEX_HOME/archived_sessions/**/*.jsonl"] if jsonl_files else []
        report.tool_call_recognizable = "yes" if any_tool else "partial_or_not_seen_in_samples"
        report.created_updated_available = "jsonl timestamp + file mtime" if any_readable else "unknown"
        report.readability = "plaintext_jsonl" if any_readable else "not_detected_or_not_readable"
        report.encryption_or_locking = "no_encryption_detected" if any_readable else "unknown"
        report.structures = structures
        if not jsonl_files:
            report.risks.append("未在标准 Codex CLI 路径发现 JSONL sessions；可能未使用 CLI/扩展，或 CODEX_HOME 不同。")
        report.risks.append("Codex JSONL 通常没有稳定 UI 标题，应以 cwd/首个用户问题作为 fallback display title，并标记 generated_fallback。")
        report.next_checks.append("如需要 Codex 支持，允许用户指定 $CODEX_HOME 或 transcript 文件夹。")
        return report

    def detect_generic(self, paths: list[Path]) -> AgentDetectReport:
        report = AgentDetectReport(agent="GenericTranscript")
        report.roots_checked = [redact_home(p) for p in paths]
        structures: dict[str, Any] = {"paths": []}
        files: list[Path] = []
        for p in paths:
            if p.is_file():
                files.append(p)
            elif p.is_dir():
                files.extend(safe_glob(p, ["*.jsonl", "*.json", "*.md", "*.txt"], max_files=1000))
        for p in files[:80]:
            item = safe_stat(p)
            if p.suffix.lower() == ".jsonl":
                item["jsonl_structure"] = inspect_jsonl(p, max_lines=300)
            elif p.suffix.lower() == ".json":
                item["json_type"] = type(read_json(p)).__name__
            else:
                item["text_like"] = True
            structures["paths"].append(item)
        report.detected = bool(files)
        report.session_count = len(files)
        report.title_count = 0
        report.missing_title_count = len(files)
        report.title_sources = ["file_name fallback only"] if files else []
        report.turn_sources = ["user supplied transcript files"] if files else []
        report.tool_call_recognizable = "depends_on_format"
        report.created_updated_available = "file mtime unless transcript has timestamp"
        report.readability = "plaintext_files" if files else "no_files"
        report.encryption_or_locking = "no_encryption_detected" if files else "unknown"
        report.structures = structures
        return report


def build_report(generic_paths: list[str]) -> dict[str, Any]:
    detector = Detector()
    path_objs = [Path(p).expanduser() for p in generic_paths]
    agents = [
        detector.detect_hanaagent(),
        detector.detect_workbuddy(),
        detector.detect_qoder(),
        detector.detect_codex(),
        detector.detect_generic(path_objs) if path_objs else AgentDetectReport(agent="GenericTranscript", detected=False),
    ]
    return {
        "report_type": "agent_source_detect",
        "generated_at": iso_now(),
        "project_root": redact_home(PROJECT_ROOT),
        "privacy_note": "This report stores structure/counts/paths only. It intentionally avoids transcript content and raw titles.",
        "trusted_source_notes": TRUSTED_SOURCE_NOTES,
        "agents": [a.to_dict() for a in agents],
        "summary": {
            "detected_agents": [a.agent for a in agents if a.detected],
            "total_sessions_seen": sum(a.session_count for a in agents),
            "total_titled_sessions_seen": sum(a.title_count for a in agents),
            "agents_with_readable_turns": [a.agent for a in agents if "jsonl" in a.readability or "plaintext" in a.readability or "sqlite" in a.readability],
        },
    }


def print_console_summary(report: dict[str, Any]) -> None:
    print("=" * 72)
    print("Memo Agent Source Detect Report")
    print(f"Generated: {report['generated_at']}")
    print(f"Privacy: {report['privacy_note']}")
    print("=" * 72)
    for agent in report["agents"]:
        print(f"\n[{agent['agent']}]")
        print(f"  detected: {agent['detected']}")
        print(f"  sessions: {agent['session_count']}")
        print(f"  titled: {agent['title_count']} / missing: {agent['missing_title_count']}")
        print(f"  title_sources: {', '.join(agent['title_sources']) or '-'}")
        print(f"  turn_sources: {', '.join(agent['turn_sources']) or '-'}")
        print(f"  readability: {agent['readability']}")
        print(f"  encryption_or_locking: {agent['encryption_or_locking']}")
        print(f"  tool_call_recognizable: {agent['tool_call_recognizable']}")
        if agent["risks"]:
            print("  risks:")
            for risk in agent["risks"][:5]:
                print(f"    - {risk}")
        if agent["next_checks"]:
            print("  next_checks:")
            for check in agent["next_checks"][:5]:
                print(f"    - {check}")
    print("\nSummary:")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="只读探测 Agent 会话来源结构，不写 Memo 数据库。")
    parser.add_argument("--generic-path", action="append", default=[], help="额外 transcript 文件或目录，可重复传入。")
    parser.add_argument("--output", default="", help="报告输出路径；默认 reports/agent-source-detect-<timestamp>.json")
    args = parser.parse_args()

    report = build_report(args.generic_path)
    print_console_summary(report)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    output = Path(args.output) if args.output else REPORTS_DIR / f"agent-source-detect-{now_stamp()}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nReport written: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
