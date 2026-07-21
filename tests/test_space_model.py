"""Context Space 基础闭环测试。"""

from memo.core.engine import engine
from memo.store.database import db


def test_space_create_bind_recall_and_todo():
    engine.init()

    space = engine.space_create(
        name="测试管理空间",
        type="management",
        description="用于验证管理型 Context Space",
        goal="验证空间闭环",
    )
    assert space["name"] == "测试管理空间"

    session = engine.start_session(title="Space 测试会话", space_id=space["id"])
    memory_id = engine.remember(
        session_id=session.id,
        raw_text="测试管理空间需要确认里程碑、风险和交付物。",
        title="管理空间闭环测试",
        summary="验证 Space 与记忆绑定",
        feature_tags=["测试管理空间", "里程碑", "交付物"],
        space_id=space["id"],
    )

    results = engine.space_recall(space["id"], "里程碑", top_k=3, mode="within")
    assert any(r["id"] == memory_id for r in results)
    assert all(r["from_current_space"] for r in results)

    todo = engine.todo_add(
        title="确认测试里程碑",
        priority="high",
        space_id=space["id"],
    )
    assert todo["space_id"] == space["id"]

    profile = engine.space_profile(space["id"])
    assert profile["status"]["total_memories"] >= 1
    assert any(t["id"] == todo["id"] for t in profile["active_todos"])


def test_space_detect_by_name():
    engine.init()
    space = engine.space_create(name="检测空间", type="personal", description="自动检测测试")
    candidates = engine.space_detect("我们继续聊检测空间的下一步安排", top_k=3)
    assert candidates
    assert candidates[0]["space_id"] == space["id"]
    assert candidates[0]["confidence"] >= 0.4


def test_space_candidate_from_session_requires_manual_accept():
    engine.init()
    session = engine.start_session(title="候选项目整理测试会话")
    memory_id = engine.remember(
        session_id=session.id,
        raw_text="候选项目整理需要基于历史会话生成 Space Candidate，并由用户查看来源证据后手动确认。",
        title="候选项目整理方案",
        summary="基于会话生成候选项目，并保留人工确认边界",
        feature_tags=["候选项目", "历史会话", "人工确认"],
    )

    scan = engine.space_candidate_scan(limit=20, min_memories=1)
    assert scan["scanned"] >= 1
    candidates = engine.space_candidate_list(limit=20)
    target = next(c for c in candidates if c["candidate_name"] == "候选项目整理测试会话")
    detail = engine.space_candidate_get(target["id"])
    assert detail["status"] == "pending"
    assert detail["source_sessions"]
    assert any(m["id"] == memory_id for m in detail["source_memories"])

    accepted = engine.space_candidate_accept(target["id"], name="候选项目整理正式空间", type="management")
    assert accepted["candidate_status"] == "accepted"
    space_results = engine.space_recall(accepted["id"], "人工确认", top_k=3, mode="within")
    assert any(r["id"] == memory_id for r in space_results)


def test_source_session_backfill_from_legacy_sessions():
    engine.init()
    session = engine.start_session(title="来源会话索引测试")
    memory_id = engine.remember(
        session_id=session.id,
        raw_text="source_sessions 只建立来源索引，不替代 sessions，也不改变记忆内容。",
        title="来源会话索引记忆",
        summary="验证 source_sessions 与 memory 映射",
        feature_tags=["source_sessions", "来源索引"],
    )

    result = engine.source_session_backfill(limit=50)
    assert result["scanned"] >= 1
    source = engine.source_session_get(session.id)
    assert source
    assert source["legacy_session_id"] == session.id
    assert source["source_type"] == "memo_session"
    assert any(m["id"] == memory_id for m in source["memories"])
    stats = engine.source_session_stats()
    assert stats["total"] >= 1


def test_space_candidate_accept_does_not_change_memory_weights():
    engine.init()
    session = engine.start_session(title="候选权重边界测试会话")
    memory_id = engine.remember(
        session_id=session.id,
        raw_text="候选项目整理只能建立 Space 归属映射，不能改变记忆权重、置顶或信号等级。",
        title="候选权重边界记忆",
        summary="确认 Space Candidate 不触碰记忆权重字段",
        feature_tags=["候选权重边界", "Space Candidate", "不改权重"],
    )
    engine.memory_govern(memory_id, "pin", user_weight=1.7, user_note="权重边界测试")
    before = dict(db.fetchone("SELECT signal_level, user_weight, pinned, status FROM memory_units WHERE id=?", (memory_id,)))

    engine.space_candidate_scan(limit=30, min_memories=1)
    candidates = engine.space_candidate_list(limit=50)
    target = next(c for c in candidates if c["candidate_name"] == "候选权重边界测试会话")
    accepted = engine.space_candidate_accept(target["id"], name="候选权重边界正式空间", type="management")
    assert accepted["candidate_status"] == "accepted"

    after = dict(db.fetchone("SELECT signal_level, user_weight, pinned, status FROM memory_units WHERE id=?", (memory_id,)))
    assert after == before


def test_space_candidate_merge_many():
    engine.init()
    s1 = engine.start_session(title="候选合并 A")
    m1 = engine.remember(
        session_id=s1.id,
        raw_text="候选合并功能需要把多个候选项目由用户手动合并为一个正式空间。",
        title="候选合并 A 记忆",
        summary="多个候选项目可手动合并为一个正式空间",
        feature_tags=["候选合并", "手动确认"],
    )
    s2 = engine.start_session(title="候选合并 B")
    m2 = engine.remember(
        session_id=s2.id,
        raw_text="多候选合并仍然需要保留来源证据，并绑定所有相关记忆。",
        title="候选合并 B 记忆",
        summary="多候选合并需要保留来源证据并绑定记忆",
        feature_tags=["候选合并", "来源证据"],
    )

    engine.space_candidate_scan(limit=20, min_memories=1)
    candidates = engine.space_candidate_list(limit=50)
    ids = [c["id"] for c in candidates if c["candidate_name"] in {"候选合并 A", "候选合并 B"}]
    assert len(ids) == 2
    merged = engine.space_candidate_merge_many(ids, name="候选合并正式空间", type="management")
    assert merged["candidate_status"] == "merged"
    results = engine.space_recall(merged["id"], "候选合并", top_k=5, mode="within")
    result_ids = {r["id"] for r in results}
    assert {m1, m2}.issubset(result_ids)
