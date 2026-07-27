import json
import subprocess
import sys
from pathlib import Path

from scripts.source_aware_import import GenericTranscriptAdapter, parse_generic_jsonl, run_dry_run


def test_parse_generic_jsonl_counts_roles_and_tools(tmp_path: Path):
    transcript = tmp_path / "session.jsonl"
    lines = [
        {"type": "message", "role": "user", "content": "请帮我分析一个长期记忆系统的架构问题"},
        {"type": "message", "role": "assistant", "content": "可以，我们先拆解底层数据结构。"},
        {"type": "tool_call", "role": "assistant", "content": [{"type": "tool_use", "name": "read"}]},
        {"type": "tool_result", "role": "tool", "content": [{"type": "tool_result", "text": "ok"}]},
    ]
    transcript.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in lines), encoding="utf-8")

    turns = parse_generic_jsonl(transcript)

    assert len(turns) == 4
    assert turns[0].role == "user"
    assert turns[1].is_final_answer is True
    assert any(t.is_tool_call for t in turns)
    assert any(t.is_tool_result for t in turns)


def test_generic_adapter_dry_run_does_not_include_raw_content(tmp_path: Path):
    transcript = tmp_path / "session.jsonl"
    secret_text = "这是不应该进入报告的原始聊天正文"
    transcript.write_text(
        json.dumps({"type": "message", "role": "user", "content": secret_text}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    report = GenericTranscriptAdapter(transcript).dry_run()
    payload = json.dumps(report.to_dict(), ensure_ascii=False)

    assert report.scanned_sessions == 1
    assert report.importable_source_sessions == 1
    assert report.source_turns == 1
    assert secret_text not in payload
    assert "content_hash" not in payload  # preview intentionally stays at aggregate/session level


def test_run_dry_run_generic(tmp_path: Path):
    transcript = tmp_path / "session.txt"
    transcript.write_text("User: 这个项目后续要保留来源会话关系\nAssistant: 好，先做 dry-run。", encoding="utf-8")

    report = run_dry_run("generic", path=str(transcript))

    assert report.source == "generic"
    assert report.scanned_sessions == 1
    assert report.estimated_episodes >= 1


def test_source_aware_import_apply_is_rejected():
    result = subprocess.run(
        [sys.executable, "scripts/source_aware_import.py", "--source", "generic", "--path", ".", "--apply"],
        cwd=Path(__file__).resolve().parent.parent,
        text=True,
        capture_output=True,
        timeout=20,
    )

    assert result.returncode == 2
    assert "只允许 --dry-run" in result.stderr
