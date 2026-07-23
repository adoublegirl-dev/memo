import json
import subprocess
import sys
from pathlib import Path

from memo.episode import EpisodeCanonicalizer, EpisodeSplitter, Turn
from memo.core.engine import Engine
from memo.store.database import db


def test_episode_splitter_creates_user_intent_boundaries():
    turns = [
        Turn(agent="test", session_id="s1", turn_id="1", role="user", content="请检查 Memo GitHub Release 是否正常"),
        Turn(agent="test", session_id="s1", turn_id="2", role="assistant", content="Release 已发布成功，两个 exe 都在。", is_final=True),
        Turn(agent="test", session_id="s1", turn_id="3", role="user", content="另外开始设计 episode memory 迁移方案"),
        Turn(agent="test", session_id="s1", turn_id="4", role="assistant", content="建议新增 schema、splitter、canonicalizer 和 dry-run 报告。", is_final=True),
    ]
    episodes = EpisodeSplitter().split(turns, source_session_id="src1", agent_name="test")
    assert len(episodes) == 2
    assert episodes[0].start_turn_id == "1"
    assert episodes[0].end_turn_id == "2"
    assert "Release" in episodes[0].title
    assert episodes[1].start_turn_id == "3"


def test_canonicalizer_recommends_high_value_release_episode():
    episode = EpisodeSplitter().split([
        Turn(agent="test", session_id="s1", turn_id="1", role="user", content="发布 Memo Desktop Companion，要求确认 GitHub Release、安装包和安全说明。"),
        Turn(agent="test", session_id="s1", turn_id="2", role="assistant", content="已完成发布。两个 exe 都在 Assets，发布包不包含 .env、data、logs、docs。", is_final=True),
    ])[0]
    draft = EpisodeCanonicalizer().canonicalize(episode)
    assert draft.long_term_value_score >= 0.45
    assert not draft.skip
    assert draft.suggested_memory_type in {"EVENT", "DECISION", "FACT"}
    assert "GitHub" in draft.feature_tags or "桌面助手" in draft.feature_tags
    assert "发布" in draft.to_memory_text()


def test_canonicalizer_marks_sensitive_episode_for_review():
    episode = EpisodeSplitter().split([
        Turn(agent="test", session_id="s1", turn_id="1", role="user", content="请记录 api_key=sk-1234567890abcdef1234567890abcdef 以后使用"),
        Turn(agent="test", session_id="s1", turn_id="2", role="assistant", content="不应把密钥作为普通长期记忆导入。", is_final=True),
    ])[0]
    draft = EpisodeCanonicalizer().canonicalize(episode)
    assert draft.skip
    assert draft.sensitive_hints


def test_schema_17_episode_tables_exist():
    db.init()
    version = db.fetchone("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1")
    assert version["version"] >= 17
    for table in ["episodes", "episode_sources", "import_runs", "canonicalization_runs"]:
        row = db.fetchone("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
        assert row is not None


def test_episode_engine_preview_does_not_initialize_database():
    engine = Engine()
    assert engine._initialized is False
    report = engine.episode_preview_turns([
        {"role": "user", "content": "继续做 episode memory Phase 2 接入"},
        {"role": "assistant", "content": "已新增 EpisodeManager 和 Engine dry-run preview 入口。", "is_final": True},
    ], source_session_id="preview-session", agent_name="test")
    assert engine._initialized is False
    assert report["dry_run"] is True
    assert report["candidate_episodes"] == 1


def test_episode_import_run_record_and_list():
    engine = Engine()
    report = engine.episode_preview_turns([
        {"role": "user", "content": "生成一次历史导入预览报告"},
        {"role": "assistant", "content": "报告只写 import_runs，不导入长期记忆。", "is_final": True},
    ], source_session_id="run-session", agent_name="test")
    saved = engine.episode_import_run_record(report, source_agent="test", source_path="memory://unit-test")
    assert saved["id"]
    assert saved["status"] == "dry_run"
    runs = engine.episode_import_run_list(limit=5, source_agent="test")
    assert any(r["id"] == saved["id"] for r in runs)
    detail = engine.episode_import_run_get(saved["id"])
    assert detail["report"]["candidate_episodes"] == 1


def test_import_agent_history_dry_run_report(tmp_path: Path):
    sample = tmp_path / "sample.jsonl"
    sample.write_text("\n".join([
        json.dumps({"role": "user", "content": "请修复 Memo schema migration 并输出 dry-run 报告。"}, ensure_ascii=False),
        json.dumps({"role": "assistant", "content": "已完成 migration 017，并且 dry-run 不会写入生产库。", "is_final": True}, ensure_ascii=False),
    ]), encoding="utf-8")
    out = tmp_path / "report.json"
    result = subprocess.run(
        [sys.executable, "scripts/import_agent_history.py", "--source", "generic", "--path", str(sample), "--output", str(out)],
        cwd=Path(__file__).resolve().parent.parent,
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["dry_run"] is True
    assert report["candidate_episodes"] == 1
    assert report["items"][0]["episodes"][0]["title"]
