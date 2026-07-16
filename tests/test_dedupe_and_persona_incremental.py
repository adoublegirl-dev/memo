"""去重闸门与人格增量候选筛选测试。"""

from datetime import datetime

from memo.core.engine import engine
from memo.models import MemoryType
from memo.store.database import db, new_id


def test_remember_conversation_exact_duplicate_skips_before_second_write():
    engine.init()
    session = engine.start_session(title="去重测试", agent_id="test-agent")
    conversation = "User: 帮我加一条测试待办，内容“今天的成果还可以，后面需要再优化”，优先级中等，截至日期2026-07-22\nAssistant: 已添加。"

    first = engine.remember_conversation(
        session_id=session.id,
        conversation=conversation,
        auto_extract=False,
        skip_gating=True,
        skip_cas=True,
    )
    second = engine.remember_conversation(
        session_id=session.id,
        conversation=conversation,
        auto_extract=False,
        skip_gating=True,
        skip_cas=True,
    )

    assert first["memory_id"]
    assert second["memory_id"] is None
    assert second["extraction_method"] in {"dedupe_skipped", "ingestion_skipped"}
    assert second["dedupe_result"]["reason"] in {"exact_normalized_duplicate", "conversation_hash_duplicate"}

    rows = db.fetchall(
        "SELECT * FROM memory_units WHERE raw_text = ?",
        (conversation,),
    )
    assert len(rows) == 1


def test_persona_incremental_skips_operational_memory(monkeypatch):
    engine.init()
    session = engine.start_session(title="人格增量跳过测试", agent_id="test-agent")
    memory_id = engine.remember(
        session_id=session.id,
        raw_text="User: 帮我创建一条测试待办。Assistant: 创建成功，ID abcdef12。",
        title="测试待办创建成功",
        summary="创建测试待办的操作确认。",
        memory_type=MemoryType.EVENT,
        feature_tags=["测试待办"],
    )

    now = datetime.now().isoformat()
    assertion_id = new_id()
    db.execute(
        """INSERT INTO persona_assertions
           (id, dimension, assertion, confidence, evidences, signal_level, created_at, updated_at, last_refreshed)
           VALUES (?, 'preference', '用户偏好简洁克制的交互设计。', 0.7, '[]', 2, ?, ?, ?)""",
        (assertion_id, now, now, now),
    )
    db.commit()

    from memo.persona import extractor

    monkeypatch.setattr(extractor.llm_client, "chat", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("operational memory should not call LLM")))
    monkeypatch.setattr(extractor.llm_client.__class__, "available", property(lambda self: True))

    result = extractor.update_persona_incremental([memory_id])

    assert result["skipped_memories"] == 1
    assert result["candidate_checks"] == 0
