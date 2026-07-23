"""Episode-level Agent 历史记忆迁移预览工具。

核心原则：不导入聊天记录本身，只从历史会话中提取长期记忆候选。

Phase 1 默认 dry-run：
- 读取 JSONL / JSON / Markdown transcript
- 标准化为 Turn
- 切分 Episode
- 生成 CanonicalMemoryDraft
- 输出 JSON 报告

后续版本再接入用户确认后的 apply。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from memo.episode import EpisodeCanonicalizer, EpisodeSplitter, Turn

DEFAULT_HANAKO_DIR = Path.home() / ".hanako" / "agents" / "hanako" / "sessions"
REPORTS_DIR = PROJECT_ROOT / "reports"


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
                elif "content" in item:
                    parts.append(_as_text(item.get("content")))
            else:
                parts.append(str(item))
        return "\n".join(p for p in parts if p)
    return str(value)


def _turn_from_obj(obj: dict, source_agent: str, fallback_session_id: str, index: int) -> Turn | None:
    # HanaAgent / Claude-like: {type: message, message:{role, content}}
    message = obj.get("message") if isinstance(obj.get("message"), dict) else obj
    role = str(message.get("role") or obj.get("role") or "").lower()
    if role not in {"user", "assistant", "tool", "system"}:
        return None
    content = _as_text(message.get("content") if "content" in message else obj.get("content")).strip()
    if not content:
        return None
    session_id = str(obj.get("session_id") or obj.get("conversation_id") or fallback_session_id)
    return Turn(
        agent=str(obj.get("agent") or source_agent),
        session_id=session_id,
        turn_id=str(obj.get("turn_id") or obj.get("id") or f"{fallback_session_id}:{index}"),
        role=role,
        content=content,
        timestamp=str(obj.get("timestamp") or obj.get("created_at") or message.get("created_at") or ""),
        tool_name=str(obj.get("tool_name") or obj.get("name") or ""),
        is_final=bool(obj.get("is_final") or obj.get("final") or False),
        metadata={"source_keys": sorted(list(obj.keys()))[:20]},
    )


def read_jsonl(path: Path, source_agent: str) -> list[Turn]:
    turns: list[Turn] = []
    fallback_session_id = path.stem
    for i, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        turn = _turn_from_obj(obj, source_agent, fallback_session_id, i)
        if turn:
            turns.append(turn)
    return turns


def read_json(path: Path, source_agent: str) -> list[Turn]:
    data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    fallback_session_id = path.stem
    if isinstance(data, dict):
        for key in ("messages", "turns", "conversation"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            data = [data]
    if not isinstance(data, list):
        return []
    turns = []
    for i, obj in enumerate(data):
        if isinstance(obj, dict):
            turn = _turn_from_obj(obj, source_agent, fallback_session_id, i)
            if turn:
                turns.append(turn)
    return turns


def read_markdown(path: Path, source_agent: str) -> list[Turn]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    pattern = re.compile(r"^(?:#{1,6}\s*)?(User|用户|Human|Assistant|助手|AI|Tool|System)\s*[:：]?\s*$", re.I | re.M)
    matches = list(pattern.finditer(text))
    turns: list[Turn] = []
    if not matches:
        return [Turn(agent=source_agent, session_id=path.stem, turn_id=f"{path.stem}:0", role="user", content=text[:20000])]
    for idx, match in enumerate(matches):
        role_label = match.group(1).lower()
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        content = text[start:end].strip()
        if not content:
            continue
        role = "assistant" if role_label in {"assistant", "助手", "ai"} else ("tool" if role_label == "tool" else ("system" if role_label == "system" else "user"))
        turns.append(Turn(agent=source_agent, session_id=path.stem, turn_id=f"{path.stem}:{idx}", role=role, content=content))
    return turns


def load_turns(path: Path, source_agent: str) -> list[Turn]:
    if path.suffix.lower() == ".jsonl":
        return read_jsonl(path, source_agent)
    if path.suffix.lower() == ".json":
        return read_json(path, source_agent)
    if path.suffix.lower() in {".md", ".markdown", ".txt"}:
        return read_markdown(path, source_agent)
    return []


def iter_files(source: str, path: Path | None) -> list[Path]:
    if path is None:
        if source == "hanaagent" and DEFAULT_HANAKO_DIR.exists():
            path = DEFAULT_HANAKO_DIR
        else:
            return []
    if path.is_file():
        return [path]
    patterns = ["*.jsonl", "*.json", "*.md", "*.txt"]
    files: list[Path] = []
    for pattern in patterns:
        files.extend(path.rglob(pattern))
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def build_report(source: str, files: list[Path], mode: str, limit: int) -> dict:
    splitter = EpisodeSplitter()
    canonicalizer = EpisodeCanonicalizer()
    report = {
        "generated_at": datetime.now().isoformat(),
        "source": source,
        "mode": mode,
        "dry_run": True,
        "scanned_files": 0,
        "scanned_turns": 0,
        "candidate_episodes": 0,
        "recommended": 0,
        "manual_review": 0,
        "skipped": 0,
        "items": [],
    }
    for path in files[:limit]:
        turns = load_turns(path, source)
        if not turns:
            continue
        episodes = splitter.split(turns, source_session_id=path.stem, agent_name=source)
        file_item = {
            "path": str(path),
            "turn_count": len(turns),
            "episode_count": len(episodes),
            "episodes": [],
        }
        report["scanned_files"] += 1
        report["scanned_turns"] += len(turns)
        for episode in episodes:
            draft = canonicalizer.canonicalize(episode)
            bucket = "skipped" if draft.skip else episode.status
            if bucket == "recommended":
                report["recommended"] += 1
            elif bucket == "manual_review":
                report["manual_review"] += 1
            else:
                report["skipped"] += 1
            report["candidate_episodes"] += 1
            file_item["episodes"].append({
                "episode_id": episode.id,
                "title": draft.title,
                "user_intent": draft.user_intent,
                "status": bucket,
                "score": draft.long_term_value_score,
                "memory_type": draft.suggested_memory_type,
                "feature_tags": draft.feature_tags,
                "key_facts": draft.key_facts,
                "final_conclusion": draft.final_conclusion,
                "decision_or_result": draft.decision_or_result,
                "sensitive_hints": draft.sensitive_hints,
                "skip_reasons": draft.skip_reasons,
                "source_turn_ids": draft.source_turn_ids[:20],
            })
        report["items"].append(file_item)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Episode-level Agent 历史记忆迁移预览（默认 dry-run）")
    parser.add_argument("--source", default="generic", choices=["generic", "hanaagent", "workbuddy", "qoder", "codex", "claude", "cursor", "auto"], help="来源 Agent")
    parser.add_argument("--path", default="", help="会话文件或目录；不传且 source=hanaagent 时尝试默认 HanaAgent sessions 目录")
    parser.add_argument("--mode", default="recommended", choices=["recommended", "comprehensive", "manual"], help="候选模式；Phase 1 仅影响报告标记")
    parser.add_argument("--limit", type=int, default=20, help="最多扫描文件数，默认 20")
    parser.add_argument("--apply", action="store_true", help="Phase 1 暂不支持。为安全起见会直接拒绝")
    parser.add_argument("--output", default="", help="报告输出路径，默认 reports/import-candidates-时间戳.json")
    args = parser.parse_args()

    if args.apply:
        print("[拒绝] Phase 1 只支持 dry-run。请先查看候选报告，后续版本再提供用户确认后的 apply。")
        return 2

    source_path = Path(args.path).expanduser() if args.path else None
    files = iter_files("hanaagent" if args.source == "auto" else args.source, source_path)
    if not files:
        print("未找到可扫描文件。请使用 --path 指向 JSONL/JSON/Markdown/TXT 文件或目录。")
        return 1

    report = build_report(args.source, files, args.mode, max(1, min(args.limit, 200)))
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = Path(args.output) if args.output else REPORTS_DIR / f"import-candidates-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"扫描文件: {report['scanned_files']}")
    print(f"扫描 turns: {report['scanned_turns']}")
    print(f"episode 候选: {report['candidate_episodes']}")
    print(f"推荐导入: {report['recommended']} / 人工确认: {report['manual_review']} / 跳过: {report['skipped']}")
    print(f"报告: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
