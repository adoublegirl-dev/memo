from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEMO_ROOT = ROOT.parent / "Memo_V0.1.0"


def test_memory_management_defaults_to_global_memory_list():
    source = (MEMO_ROOT / "src" / "routes" / "Memories.svelte").read_text(encoding="utf-8")
    assert "if (sourceSessionId) params.source_session_id = sourceSessionId" in source
    assert "Promise.all([loadSourceSessions(), loadOverview(), load()])" in source
    assert "包括Codex等MCP手动写入" in source
    assert "if (!sourceSessionId)" not in source


def test_governance_defaults_to_created_dedupe_records_not_duplicate_groups():
    source = (MEMO_ROOT / "src" / "routes" / "Governance.svelte").read_text(encoding="utf-8")
    assert "let activeTab = 'dedupe_records'" in source
    assert "不代表记忆库为空" in source
