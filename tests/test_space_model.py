"""Context Space 基础闭环测试。"""

from memo.core.engine import engine


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
