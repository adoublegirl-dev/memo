"""P1-P3 增强闭环测试。"""

from memo.core.engine import engine
from memo.models import MemoryType


def test_ingestion_memory_link_space_duplicate_and_summary():
    engine.init()

    # Space alias / similarity duplicate
    space = engine.space_create(name="Memo治理空间", type="management", aliases=["记忆治理空间"], goal="治理记忆质量")
    duplicate = engine.space_create(name="记忆治理空间", type="management")
    assert duplicate["id"] == space["id"]
    assert duplicate["created"] is False

    session = engine.start_session(title="P1P3 测试", space_id=space["id"])
    a = engine.remember(
        session_id=session.id,
        raw_text="Memo 治理需要追踪重复输入、合并链和空间简报。",
        title="Memo治理基础",
        summary="追踪重复输入、合并链和空间简报。",
        feature_tags=["Memo治理", "合并链"],
        space_id=space["id"],
    )
    b = engine.remember(
        session_id=session.id,
        raw_text="重复记忆应该能合并到更完整的记忆中。",
        title="重复记忆合并",
        summary="验证 MERGED_INTO 关系。",
        feature_tags=["重复记忆", "合并链"],
        space_id=space["id"],
    )

    link = engine.memory_link(b, a, relation_type="MERGED_INTO", reason="测试合并链")
    assert link["linked"] is True
    links = engine.memory_links(a)
    assert any(l["source_memory_id"] == b and l["target_memory_id"] == a for l in links)

    profile = engine.space_profile(space["id"], mode="handoff", persist=True)
    assert "summary_text" in profile
    assert "交接" in profile["summary_text"]

    overview = engine.governance_overview(limit=10)
    assert "memory_links" in overview
    assert "source_groups" in overview
    assert any(l["target_memory_id"] == a for l in overview["memory_links"])


def test_governance_source_groups_collapses_same_raw_text():
    engine.init()
    session = engine.start_session(title="同源分组测试", agent_id="test-agent")
    raw = "User: 同一段原始对话可能被抽成推理和决策\nAssistant: 应该按同源输入聚合展示。"
    a = engine.remember(
        session_id=session.id,
        raw_text=raw,
        title="同源推理",
        summary="按同源输入聚合。",
        memory_type=MemoryType.REASONING,
    )
    b = engine.remember(
        session_id=session.id,
        raw_text=raw,
        title="同源决策",
        summary="分类不同也不平铺展示。",
        memory_type=MemoryType.DECISION,
    )
    overview = engine.governance_overview(limit=20)
    groups = overview["source_groups"]
    group = next(g for g in groups if {m["id"] for m in g["members"]} >= {a, b})
    assert group["count"] == 2
    assert group["canonical_id"] == b
    assert sorted(group["memory_types"]) == ["DECISION", "REASONING"]
