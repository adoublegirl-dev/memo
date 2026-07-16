"""记忆治理基础测试。"""

from memo.core.engine import engine


def test_memory_governance_pin_wrong_restore():
    engine.init()
    session = engine.start_session(title="记忆治理测试")
    memory_id = engine.remember(
        session_id=session.id,
        raw_text="这是一条用于记忆治理的测试记忆。",
        title="记忆治理测试",
        summary="验证标重要、错误和恢复。",
        feature_tags=["记忆治理"],
    )

    pinned = engine.memory_govern(memory_id, "pin", note="重要")
    assert pinned["updated"] is True
    results = engine.recall("记忆治理", top_k=5)
    mem = next(r for r in results if r["id"] == memory_id)
    assert mem["pinned"] is True

    wrong = engine.memory_govern(memory_id, "mark_wrong", note="测试错误")
    assert wrong["updated"] is True
    results = engine.recall("记忆治理", top_k=5)
    assert all(r["id"] != memory_id for r in results)

    restored = engine.memory_govern(memory_id, "restore", note="恢复测试")
    assert restored["updated"] is True
    results = engine.recall("记忆治理", top_k=5)
    assert any(r["id"] == memory_id for r in results)

    audit = engine.memory_audit(memory_id)
    assert len(audit) >= 3
