"""人格提炼器 —— 批量建基线 + 增量更新。

批量提炼（模式 B）：采样 L2+L1+高价值 L0 记忆 → 10 维逐维提炼 → 初始断言
增量更新（模式 A/B 通用）：新记忆逐条检查 → 印证/补充/推翻已有断言
"""

from datetime import datetime
from typing import Any

from memo.core.config import config
from memo.store.database import db, new_id
from memo.utils.llm import llm_client
from memo.utils.embedding import embedding_model
from memo.utils.logger import logger

# 10 维定义
DIMENSIONS = [
    ("value", "核心价值观——什么对用户来说最重要，不可触碰的底线"),
    ("decision", "决策模式——用户做判断和选择时的一贯方式"),
    ("identity", "身份标签——用户对自己的定位和角色认知"),
    ("preference", "偏好倾向——用户的审美、工具、流程方面的喜好"),
    ("sensitivity", "敏感话题——用户反复提及或情绪反应强烈的主题"),
    ("relationship", "关系强度——用户对不同项目/人物/概念的关注优先级"),
    ("knowledge", "知识边界——用户明确知道/不知道的技术领域"),
    ("communication", "沟通风格——用户偏好的表达方式、语气、信息密度"),
    ("mental_model", "思维模型——用户分析和拆解问题的底层框架"),
    ("emotion", "情绪特征——用户在不同场景下的情绪反应模式"),
]

# 批量提炼参数
MAX_SAMPLES_PER_DIM = 30
MAX_TOKEN_CHARS = 20000
BASELINE_CONFIDENCE_L2 = 0.70
BASELINE_CONFIDENCE_L1_CROSS = 0.50
BASELINE_CONFIDENCE_SINGLE = 0.30


def _sample_memories_for_baseline() -> list[dict]:
    """采样记忆用于批量建基线。

    策略：L2 全部 + L1 全部 + L0 中 gating_score 前 20%。
    """
    # 获取所有活跃记忆
    rows = db.fetchall("""
        SELECT mu.id, mu.title, mu.summary, mu.summary_detail, mu.raw_text,
               mu.memory_type, mu.signal_level, mu.confidence, mu.created_at
        FROM memory_units mu
        WHERE mu.is_superseded = 0
        ORDER BY mu.signal_level DESC, mu.confidence DESC
    """)

    l2 = [r for r in rows if r["signal_level"] >= 2]
    l1 = [r for r in rows if r["signal_level"] == 1]
    l0 = [r for r in rows if r["signal_level"] == 0]

    # L0 取前 20%
    l0_sampled = l0[: max(1, int(len(l0) * 0.2))]

    sampled = l2 + l1 + l0_sampled
    logger.info(
        f"采样: L2={len(l2)} L1={len(l1)} L0={len(l0_sampled)}/{len(l0)} 总计={len(sampled)}"
    )
    return sampled


def _build_dimension_prompt(dimension: str, description: str, memories: list[dict]) -> str:
    """构建单维提炼 prompt。"""
    # 截断记忆文本到 token 上限
    chars = 0
    mem_texts = []
    for m in memories:
        text = f"[记忆ID: {m['id'][:8]}] {m['raw_text'] or m['summary_detail'] or m['summary'] or ''}"
        if chars + len(text) > MAX_TOKEN_CHARS:
            break
        mem_texts.append(text)
        chars += len(text)

    joined = "\n\n---\n\n".join(mem_texts)
    return f"""你是用户的人格分析师。请基于以下对话记录，提炼用户在「{dimension}（{description}）」维度的断言。

要求：
1. 输出 JSON 数组，每条断言包含 assertion（一句话结论）、confidence（0~1）、evidences（引用的记忆ID列表）。
2. 每条断言必须基于具体证据，不能凭空编造。如果某个子方向证据不足，可以只输出一条。
3. 置信度规则：多条独立记忆互相印证 ≥0.7，2-3 条相关记忆 ≥0.5，单条记忆支撑 =0.3。
4. 避免空洞结论（如"用户重视质量"），要具体（如"用户对数据治理的执行顺序极其敏感，容不得逻辑错误"）。

对话记录：
{joined}

请只输出 JSON 数组，不要有其他内容。"""


def build_persona_baseline() -> dict[str, Any]:
    """批量提炼：从采样记忆建人格基线。

    Returns:
        {"assertions_created": N, "dimensions_covered": [...], "total_confidence": float}
    """
    if not llm_client.available:
        logger.warning("LLM 不可用，跳过人格基线构建")
        return {"assertions_created": 0, "dimensions_covered": [], "total_confidence": 0.0}

    sampled = _sample_memories_for_baseline()
    if not sampled:
        logger.info("无可用记忆，跳过基线构建")
        return {"assertions_created": 0, "dimensions_covered": [], "total_confidence": 0.0}

    total_created = 0
    dimensions_covered = []
    total_conf = 0.0

    for dim_key, dim_desc in DIMENSIONS:
        logger.info(f"提炼维度: {dim_key}")
        try:
            prompt = _build_dimension_prompt(dim_key, dim_desc, sampled)
            response = llm_client.chat(
                messages=[{"role": "user", "content": prompt}],
                model=config.gating_model,
                temperature=0.3,
                max_tokens=2000,
            )

            # 解析 JSON
            import json, re
            json_match = re.search(r"\[.*?\]", response, re.DOTALL)
            if not json_match:
                logger.warning(f"维度 {dim_key} 未返回有效 JSON，跳过")
                continue

            assertions = json.loads(json_match.group())
            for a in assertions:
                assertion_text = a.get("assertion", "").strip()
                if not assertion_text or len(assertion_text) < 10:
                    continue

                confidence = float(a.get("confidence", BASELINE_CONFIDENCE_SINGLE))
                evidences = json.dumps(a.get("evidences", []))

                aid = new_id()
                now = datetime.now().isoformat()
                db.execute(
                    """INSERT INTO persona_assertions
                       (id, dimension, assertion, confidence, evidences, signal_level,
                        created_at, updated_at, last_refreshed)
                       VALUES (?, ?, ?, ?, ?, 2, ?, ?, ?)""",
                    (aid, dim_key, assertion_text, confidence, evidences, now, now, now),
                )
                total_created += 1
                total_conf += confidence

            db.commit()
            dimensions_covered.append(dim_key)
            logger.info(f"  维度 {dim_key}: {len(assertions)} 条断言")

        except Exception as e:
            logger.error(f"维度 {dim_key} 提炼失败: {e}")
            continue

    # 更新配置
    now = datetime.now().isoformat()
    db.execute(
        "INSERT OR REPLACE INTO persona_settings (key, value) VALUES (?, ?)",
        ("last_baseline_at", now),
    )
    db.execute(
        "INSERT OR REPLACE INTO persona_settings (key, value) VALUES (?, ?)",
        ("last_incremental_at", now),
    )
    db.commit()

    avg_conf = total_conf / total_created if total_created > 0 else 0.0
    logger.info(f"基线完成: {total_created} 条断言, 覆盖 {len(dimensions_covered)} 维, 均置信度 {avg_conf:.2f}")

    return {
        "assertions_created": total_created,
        "dimensions_covered": dimensions_covered,
        "total_confidence": round(avg_conf, 3),
    }


def update_persona_incremental(new_memory_ids: list[str] | None = None) -> dict[str, Any]:
    """增量更新：检查新记忆是否影响已有断言。

    Args:
        new_memory_ids: 新记忆 ID 列表，None 则自动查上次刷新后的所有新增

    Returns:
        {"updated": N, "new": N, "superseded": N, "unchanged": N}
    """
    if not llm_client.available:
        return {"updated": 0, "new": 0, "superseded": 0, "unchanged": 0}

    # 获取上次刷新时间
    row = db.fetchone(
        "SELECT value FROM persona_settings WHERE key = 'last_incremental_at'"
    )
    last_refresh = row["value"] if row and row["value"] else ""

    if new_memory_ids is None:
        if last_refresh:
            rows = db.fetchall(
                """SELECT id, title, summary, raw_text, signal_level
                   FROM memory_units
                   WHERE created_at > ? AND is_superseded = 0
                   ORDER BY created_at""",
                (last_refresh,),
            )
        else:
            rows = db.fetchall(
                """SELECT id, title, summary, raw_text, signal_level
                   FROM memory_units
                   WHERE is_superseded = 0
                   ORDER BY created_at DESC LIMIT 50"""
            )
        new_memory_ids = [r["id"] for r in rows]
        new_memories = [dict(r) for r in rows]
    else:
        # TODO: 按 ID 列表查询
        new_memories = []

    if not new_memories:
        return {"updated": 0, "new": 0, "superseded": 0, "unchanged": 0}

    # 获取所有活跃断言
    assertions = db.fetchall(
        "SELECT * FROM persona_assertions WHERE is_superseded = 0 AND locked = 0"
    )
    if not assertions:
        # 还没有基线，采集足够记忆后自动建基线
        total = db.fetchone("SELECT COUNT(*) as cnt FROM memory_units WHERE is_superseded = 0")
        if total["cnt"] >= 10:
            logger.info("记忆数达标，自动建基线")
            return build_persona_baseline()
        return {"updated": 0, "new": 0, "superseded": 0, "unchanged": 0}

    updated = 0
    new_assertions = 0
    superseded_count = 0
    unchanged = 0

    for mem in new_memories:
        mem_text = mem["raw_text"] or mem["summary"] or ""
        if len(mem_text) < 50:
            continue

        # 对每条断言检查新记忆是否影响它
        for a in assertions:
            try:
                prompt = f"""你是用户的人格分析师。现有一条已有的人格断言，以及一条新的对话记忆。
请判断新记忆对这条断言的影响。

已有断言（维度={a['dimension']}）：
"{a['assertion']}"

新记忆：
"{mem_text[:2000]}"

请输出 JSON：
{{"impact": "confirm|refine|supersede|none", "reason": "简短说明", "new_confidence_delta": 0.05 或 -0.1}}"""

                response = llm_client.chat(
                    messages=[{"role": "user", "content": prompt}],
                    model=config.gating_model,
                    temperature=0.2,
                    max_tokens=200,
                )

                import json, re
                json_match = re.search(r"\{.*?\}", response, re.DOTALL)
                if not json_match:
                    continue
                result = json.loads(json_match.group())
                impact = result.get("impact", "none")

                if impact == "confirm":
                    new_conf = min(1.0, a["confidence"] + result.get("new_confidence_delta", 0.05))
                    evs = json.loads(a["evidences"] or "[]")
                    if mem["id"] not in evs:
                        evs.append(mem["id"])
                    db.execute(
                        """UPDATE persona_assertions
                           SET confidence = ?, evidences = ?, updated_at = ?, last_refreshed = ?
                           WHERE id = ?""",
                        (new_conf, json.dumps(evs), datetime.now().isoformat(),
                         datetime.now().isoformat(), a["id"]),
                    )
                    updated += 1

                elif impact == "supersede":
                    db.execute(
                        "UPDATE persona_assertions SET is_superseded = 1, superseded_by = ? WHERE id = ?",
                        (mem["id"], a["id"]),
                    )
                    superseded_count += 1

                elif impact == "refine":
                    # 补充新断言，低置信度
                    aid = new_id()
                    now = datetime.now().isoformat()
                    dim = a["dimension"]
                    new_assertion_text = f"{a['assertion']}（补充：{result.get('reason', '新信息')}）"
                    db.execute(
                        """INSERT INTO persona_assertions
                           (id, dimension, assertion, confidence, evidences, signal_level,
                            created_at, updated_at, last_refreshed)
                           VALUES (?, ?, ?, 0.35, ?, 0, ?, ?, ?)""",
                        (aid, dim, new_assertion_text, json.dumps([mem["id"]]), now, now, now),
                    )
                    new_assertions += 1

                else:
                    unchanged += 1

            except Exception as e:
                logger.debug(f"增量检查异常: {e}")
                continue

    db.commit()

    # 更新时间戳
    now = datetime.now().isoformat()
    db.execute(
        "INSERT OR REPLACE INTO persona_settings (key, value) VALUES (?, ?)",
        ("last_incremental_at", now),
    )
    db.commit()

    logger.info(f"增量完成: 印证{updated} 推翻{superseded_count} 新增{new_assertions} 未变{unchanged}")
    return {
        "updated": updated,
        "new": new_assertions,
        "superseded": superseded_count,
        "unchanged": unchanged,
    }


def get_active_assertions(dimension: str | None = None) -> list[dict]:
    """获取活跃的人格断言。

    Args:
        dimension: 限定维度，None 则返回全部
    """
    if dimension:
        rows = db.fetchall(
            """SELECT * FROM persona_assertions
               WHERE is_superseded = 0 AND dimension = ?
               ORDER BY confidence DESC""",
            (dimension,),
        )
    else:
        rows = db.fetchall(
            """SELECT * FROM persona_assertions
               WHERE is_superseded = 0
               ORDER BY dimension, confidence DESC"""
        )
    return [dict(r) for r in rows]


def get_persona_settings() -> dict[str, str]:
    """获取人格设置。"""
    rows = db.fetchall("SELECT key, value FROM persona_settings")
    return {r["key"]: r["value"] for r in rows}


def get_sensitivity_level() -> float:
    """获取当前灵敏度等级对应的阈值。"""
    settings = get_persona_settings()
    level = int(settings.get("sensitivity_level", "2"))
    thresholds = {1: 0.15, 2: 0.30, 3: 0.50, 4: 0.65, 5: 0.80}
    return thresholds.get(level, 0.30)
