"""人格提炼器 —— 批量建基线 + 增量更新。

批量提炼（模式 B）：采样 L2+L1+高价值 L0 记忆 → 10 维逐维提炼 → 初始断言
增量更新（模式 A/B 通用）：新记忆逐条检查 → 印证/补充/推翻已有断言
"""

import json
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
PERSONA_DUP_SIM_THRESHOLD = 0.88


def _audit_persona(assertion_id: str, action: str, old_value: str = "", new_value: str = "", actor: str = "system", note: str = "") -> None:
    db.execute(
        """INSERT INTO persona_audit_logs (assertion_id, action, old_value, new_value, actor, note, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (assertion_id, action, old_value, new_value, actor, note, datetime.now().isoformat()),
    )


def _merge_or_insert_assertion(
    dimension: str,
    assertion_text: str,
    confidence: float,
    evidences: list[str] | None = None,
    signal_level: int = 0,
    actor: str = "persona",
    merge_existing: bool = True,
) -> tuple[str, bool]:
    """同维人格断言去重：相似则合并证据和置信度，否则新增。"""
    evidences = evidences or []
    rows = db.fetchall(
        "SELECT * FROM persona_assertions WHERE dimension = ? AND is_superseded = 0 AND locked = 0",
        (dimension,),
    ) if merge_existing else []
    if rows:
        new_vec = embedding_model.encode(assertion_text)
        best = None
        best_score = 0.0
        for r in rows:
            sim = embedding_model.cosine_similarity(new_vec, embedding_model.encode(r["assertion"]))
            if sim > best_score:
                best_score, best = sim, r
        if best and best_score >= PERSONA_DUP_SIM_THRESHOLD:
            old_evs = json.loads(best["evidences"] or "[]")
            merged_evs = list(dict.fromkeys(old_evs + evidences))
            new_conf = min(1.0, max(float(best["confidence"]), confidence) + 0.03)
            db.execute(
                """UPDATE persona_assertions
                   SET confidence = ?, evidences = ?, updated_at = ?, last_refreshed = ?
                   WHERE id = ?""",
                (new_conf, json.dumps(merged_evs), datetime.now().isoformat(), datetime.now().isoformat(), best["id"]),
            )
            _audit_persona(best["id"], "merge_similar", best["assertion"], assertion_text, actor, f"similarity={best_score:.3f}")
            return best["id"], False

    aid = new_id()
    now = datetime.now().isoformat()
    db.execute(
        """INSERT INTO persona_assertions
           (id, dimension, assertion, confidence, evidences, signal_level,
            created_at, updated_at, last_refreshed)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (aid, dimension, assertion_text, confidence, json.dumps(evidences), signal_level, now, now, now),
    )
    _audit_persona(aid, "create", "", assertion_text, actor, "inserted")
    return aid, True


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
1. 输出严格 JSON 对象，格式为 {{"assertions":[...]}}。
2. assertions 数组中每条断言包含 assertion（一句话结论）、confidence（0~1）、evidences（引用的记忆ID列表）。
3. 每条断言必须基于具体证据，不能凭空编造。如果某个子方向证据不足，可以只输出一条。
4. 置信度规则：多条独立记忆互相印证 ≥0.7，2-3 条相关记忆 ≥0.5，单条记忆支撑 =0.3。
5. 避免空洞结论（如"用户重视质量"），要具体（如"用户对数据治理的执行顺序极其敏感，容不得逻辑错误"）。

对话记录：
{joined}

请只输出严格 JSON 对象，不要输出 Markdown，不要输出解释。"""


def build_persona_baseline(reset_existing: bool = False) -> dict[str, Any]:
    """批量提炼：从采样记忆建人格基线。

    Args:
        reset_existing: True 时重建系统生成的人格基线。先生成新断言，成功后再归档旧的系统断言；自定义/锁定断言保留。

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

    old_system_rows = db.fetchall(
        "SELECT id, assertion FROM persona_assertions WHERE is_superseded = 0 AND COALESCE(is_custom,0) = 0 AND COALESCE(locked,0) = 0"
    ) if reset_existing else []
    old_system_ids = [r["id"] for r in old_system_rows]

    total_created = 0
    dimensions_covered = []
    total_conf = 0.0
    created_ids: list[str] = []
    llm_errors = 0
    last_error = ""

    for dim_key, dim_desc in DIMENSIONS:
        logger.info(f"提炼维度: {dim_key}")
        try:
            prompt = _build_dimension_prompt(dim_key, dim_desc, sampled)
            response = llm_client.chat(
                messages=[{"role": "user", "content": prompt}],
                model=config.gating_model,
                temperature=0.3,
                max_tokens=2000,
                response_format={"type": "json_object"},
            )

            # 解析 JSON。优先使用 {"assertions": [...]}，兼容旧的数组输出。
            import json, re
            try:
                parsed = json.loads(response)
            except Exception:
                obj_match = re.search(r"\{.*\}", response, re.DOTALL)
                arr_match = re.search(r"\[.*\]", response, re.DOTALL)
                if obj_match:
                    parsed = json.loads(obj_match.group())
                elif arr_match:
                    parsed = json.loads(arr_match.group())
                else:
                    logger.warning(f"维度 {dim_key} 未返回有效 JSON，跳过")
                    continue
            assertions = parsed.get("assertions", []) if isinstance(parsed, dict) else parsed
            if not isinstance(assertions, list):
                logger.warning(f"维度 {dim_key} JSON 中缺少 assertions 数组，跳过")
                continue
            for a in assertions:
                assertion_text = a.get("assertion", "").strip()
                if not assertion_text or len(assertion_text) < 10:
                    continue

                confidence = float(a.get("confidence", BASELINE_CONFIDENCE_SINGLE))
                evidences = a.get("evidences", [])
                assertion_id, created = _merge_or_insert_assertion(
                    dim_key,
                    assertion_text,
                    confidence,
                    evidences=evidences,
                    signal_level=2,
                    actor="persona_rebuild" if reset_existing else "persona_baseline",
                    merge_existing=not reset_existing,
                )
                if created:
                    total_created += 1
                    created_ids.append(assertion_id)
                total_conf += confidence

            db.commit()
            dimensions_covered.append(dim_key)
            logger.info(f"  维度 {dim_key}: {len(assertions)} 条断言")

        except Exception as e:
            llm_errors += 1
            last_error = str(e)
            logger.error(f"维度 {dim_key} 提炼失败: {e}")
            continue

    # 重建模式：只有成功生成新断言后，才归档旧系统断言，避免 Key/模型故障把画像清空。
    now = datetime.now().isoformat()
    archived_old = 0
    if reset_existing and total_created > 0 and old_system_ids:
        placeholders = ",".join("?" * len(old_system_ids))
        db.execute(
            f"UPDATE persona_assertions SET is_superseded=1, superseded_by=?, updated_at=? WHERE id IN ({placeholders})",
            tuple([f"persona_rebuild:{now}", now] + old_system_ids),
        )
        archived_old = len(old_system_ids)
        for row in old_system_rows:
            _audit_persona(row["id"], "rebuild_archive", row["assertion"], "", "persona_rebuild", "重建人格基线时归档旧系统断言")

    # 更新配置
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

    status = "updated" if total_created > 0 else ("error" if llm_errors else "noop")
    reason = "baseline_rebuilt" if reset_existing and total_created > 0 else "baseline_created" if total_created > 0 else "llm_failed" if llm_errors else "no_assertions_created"
    message = (
        f"人格基线重建完成：新增 {total_created} 条断言，归档旧系统断言 {archived_old} 条。"
        if reset_existing and total_created > 0 else
        f"人格基线提炼完成：新增 {total_created} 条断言。"
        if total_created > 0 else
        f"人格基线提炼失败或无有效输出。最近错误：{last_error[:220]}"
        if llm_errors else
        "人格基线提炼完成，但模型没有返回可用断言。"
    )
    return {
        "assertions_created": total_created,
        "dimensions_covered": dimensions_covered,
        "total_confidence": round(avg_conf, 3),
        "archived_old": archived_old,
        "created_ids": created_ids,
        "llm_errors": llm_errors,
        "last_error": last_error[:500],
        "status": status,
        "reason": reason,
        "message": message,
    }


def update_persona_incremental(new_memory_ids: list[str] | None = None) -> dict[str, Any]:
    """增量更新：检查新记忆是否影响已有断言。

    Args:
        new_memory_ids: 新记忆 ID 列表，None 则自动查上次刷新后的所有新增

    Returns:
        {"updated": N, "new": N, "superseded": N, "unchanged": N}
    """
    if not llm_client.available:
        return {
            "updated": 0,
            "new": 0,
            "superseded": 0,
            "unchanged": 0,
            "status": "blocked",
            "reason": "llm_unavailable",
            "message": "LLM 未配置，无法进行人格增量提炼。请先配置 LLM_API_KEY。",
            "llm_available": False,
        }

    # 获取上次刷新时间
    row = db.fetchone(
        "SELECT value FROM persona_settings WHERE key = 'last_incremental_at'"
    )
    last_refresh = row["value"] if row and row["value"] else ""

    if new_memory_ids is None:
        if last_refresh:
            rows = db.fetchall(
                """SELECT id, title, summary, raw_text, signal_level, memory_type
                   FROM memory_units
                   WHERE created_at > ? AND is_superseded = 0
                   ORDER BY created_at""",
                (last_refresh,),
            )
        else:
            rows = db.fetchall(
                """SELECT id, title, summary, raw_text, signal_level, memory_type
                   FROM memory_units
                   WHERE is_superseded = 0
                   ORDER BY created_at DESC LIMIT 50"""
            )
        new_memory_ids = [r["id"] for r in rows]
        new_memories = [dict(r) for r in rows]
    else:
        if not new_memory_ids:
            new_memories = []
        else:
            placeholders = ",".join("?" * len(new_memory_ids))
            rows = db.fetchall(
                f"""SELECT id, title, summary, raw_text, signal_level, memory_type
                    FROM memory_units
                    WHERE id IN ({placeholders}) AND is_superseded = 0""",
                tuple(new_memory_ids),
            )
            new_memories = [dict(r) for r in rows]

    if not new_memories:
        return {
            "updated": 0,
            "new": 0,
            "superseded": 0,
            "unchanged": 0,
            "status": "noop",
            "reason": "no_new_memories",
            "message": "没有发现上次刷新后新增的记忆，人格画像无需更新。",
            "llm_available": True,
            "candidate_memories": 0,
        }

    # 获取所有活跃断言
    assertions = db.fetchall(
        "SELECT * FROM persona_assertions WHERE is_superseded = 0 AND locked = 0"
    )
    if not assertions:
        # 还没有基线，采集足够记忆后自动建基线
        total = db.fetchone("SELECT COUNT(*) as cnt FROM memory_units WHERE is_superseded = 0")
        if total["cnt"] >= 10:
            logger.info("记忆数达标，自动建基线")
            result = build_persona_baseline()
            return {
                **result,
                "status": "updated" if result.get("assertions_created") else "noop",
                "reason": "baseline_created" if result.get("assertions_created") else "baseline_no_changes",
                "message": f"人格基线提炼完成，新增 {result.get('assertions_created', 0)} 条断言。",
                "llm_available": True,
            }
        return {
            "updated": 0,
            "new": 0,
            "superseded": 0,
            "unchanged": 0,
            "status": "noop",
            "reason": "not_enough_memories_for_baseline",
            "message": "当前还没有可增量更新的人格基线，且记忆数量不足以自动建立基线。",
            "llm_available": True,
        }

    updated = 0
    new_assertions = 0
    superseded_count = 0
    unchanged = 0
    skipped_memories = 0
    candidate_checks = 0
    llm_errors = 0
    last_error = ""
    top_k_assertions = 8

    assertion_dicts = [dict(a) for a in assertions]

    def _rank_relevant_assertions(mem_text: str) -> list[dict]:
        """用本地 embedding 先筛出最相关的人格断言，避免全量 LLM 扫描。"""
        if not assertion_dicts:
            return []
        mem_vec = embedding_model.encode(mem_text[:1500])
        scored = []
        for a in assertion_dicts:
            a_text = f"{a['dimension']}: {a['assertion']}"
            a_vec = embedding_model.encode(a_text)
            sim = embedding_model.cosine_similarity(mem_vec, a_vec)
            scored.append((max(0, sim), a))
        scored.sort(key=lambda x: x[0], reverse=True)
        # 低相关断言不进入 LLM；但至少保留 top_k 里有基本相关性的候选。
        return [a for score, a in scored[:top_k_assertions] if score >= 0.12]

    for mem in new_memories:
        mem_text = mem["raw_text"] or mem["summary"] or ""
        if len(mem_text) < 50:
            skipped_memories += 1
            continue

        from memo.dedupe.normalizer import is_persona_relevant
        if not is_persona_relevant(
            mem_text,
            title=mem.get("title", ""),
            summary=mem.get("summary", ""),
            memory_type=mem.get("memory_type", ""),
            signal_level=int(mem.get("signal_level", 0) or 0),
        ):
            skipped_memories += 1
            continue

        relevant_assertions = _rank_relevant_assertions(mem_text)
        if not relevant_assertions:
            skipped_memories += 1
            continue

        # 只对 top8 相关断言检查新记忆是否影响它。
        for a in relevant_assertions:
            candidate_checks += 1
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
                    _audit_persona(a["id"], "supersede", a["assertion"], mem["id"], "persona_incremental", result.get("reason", ""))
                    superseded_count += 1

                elif impact == "refine":
                    # 补充新断言，低置信度；若同维相似则合并证据。
                    dim = a["dimension"]
                    new_assertion_text = f"{a['assertion']}（补充：{result.get('reason', '新信息')}）"
                    _, created = _merge_or_insert_assertion(
                        dim,
                        new_assertion_text,
                        0.35,
                        evidences=[mem["id"]],
                        signal_level=0,
                        actor="persona_incremental",
                    )
                    if created:
                        new_assertions += 1

                else:
                    unchanged += 1

            except Exception as e:
                llm_errors += 1
                last_error = str(e)
                logger.warning(f"人格增量检查 LLM 调用异常: {e}")
                continue

    db.commit()

    # 更新时间戳。若所有候选 LLM 调用都失败，不推进游标，方便修好 Key 后重试。
    now = datetime.now().isoformat()
    cursor_advanced = candidate_checks == 0 or llm_errors < candidate_checks
    if cursor_advanced:
        db.execute(
            "INSERT OR REPLACE INTO persona_settings (key, value) VALUES (?, ?)",
            ("last_incremental_at", now),
        )
        db.commit()

    if candidate_checks > 0 and llm_errors >= candidate_checks:
        status = "error"
        reason = "llm_failed"
        message = f"人格增量提炼调用 LLM 失败，未推进刷新游标。请检查模型 Base URL / API Key / 模型名。最近错误：{last_error[:220]}"
    elif updated or new_assertions or superseded_count:
        status = "updated"
        reason = "changed"
        message = f"人格画像已更新：印证 {updated} 条，新增 {new_assertions} 条，推翻 {superseded_count} 条。"
    elif candidate_checks == 0:
        status = "noop"
        reason = "no_persona_relevant_candidates"
        message = f"扫描了 {len(new_memories)} 条新记忆，但没有命中需要 LLM 判断的人格相关候选。"
    else:
        status = "noop"
        reason = "no_assertion_changes"
        message = f"已检查 {candidate_checks} 个候选关系，没有发现需要改写的人格断言。"

    result_payload = {
        "updated": updated,
        "new": new_assertions,
        "superseded": superseded_count,
        "unchanged": unchanged,
        "skipped_memories": skipped_memories,
        "candidate_checks": candidate_checks,
        "llm_errors": llm_errors,
        "last_error": last_error[:500],
        "cursor_advanced": cursor_advanced,
        "candidate_memories": len(new_memories),
        "top_k_assertions": top_k_assertions,
        "llm_available": True,
        "status": status,
        "reason": reason,
        "message": message,
    }
    try:
        full_scan_estimate = len(new_memories) * len(assertion_dicts)
        db.execute(
            """INSERT INTO persona_update_runs
               (id, new_memories, skipped_memories, candidate_checks, llm_calls_estimated,
                saved_calls_estimated, top_k_assertions, result_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                new_id(), len(new_memories), skipped_memories, candidate_checks, candidate_checks,
                max(0, full_scan_estimate - candidate_checks), top_k_assertions,
                json.dumps(result_payload, ensure_ascii=False), datetime.now().isoformat(),
            ),
        )
        db.commit()
    except Exception as e:
        logger.debug(f"人格增量成本统计记录失败: {e}")

    logger.info(
        f"增量完成: 印证{updated} 推翻{superseded_count} 新增{new_assertions} "
        f"未变{unchanged} 跳过记忆{skipped_memories} LLM候选{candidate_checks}"
    )
    return result_payload


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


def get_persona_audit(assertion_id: str = "", limit: int = 50) -> list[dict[str, Any]]:
    """获取人格断言审计日志。"""
    if assertion_id:
        rows = db.fetchall(
            """SELECT * FROM persona_audit_logs
               WHERE assertion_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (assertion_id, limit),
        )
    else:
        rows = db.fetchall(
            """SELECT * FROM persona_audit_logs
               ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        )
    return [dict(r) for r in rows]


def persona_assertion_action(
    assertion_id: str,
    action: str,
    assertion: str = "",
    confidence: float | None = None,
    actor: str = "dashboard",
    note: str = "",
) -> dict[str, Any]:
    """人格断言编辑 / 锁定 / 软删除 / 恢复，并写入审计日志。"""
    row = db.fetchone("SELECT * FROM persona_assertions WHERE id = ?", (assertion_id,))
    if not row:
        return {"error": "not found"}
    old = dict(row)
    now = datetime.now().isoformat()
    action = (action or "").strip().lower()

    if action == "edit":
        changes = []
        if assertion and assertion != old.get("assertion"):
            db.execute("UPDATE persona_assertions SET assertion=?, updated_at=?, last_refreshed=? WHERE id=?", (assertion, now, now, assertion_id))
            _audit_persona(assertion_id, "edit_assertion", old.get("assertion", ""), assertion, actor, note)
            changes.append("assertion")
        if confidence is not None and float(confidence) != float(old.get("confidence") or 0):
            new_conf = max(0.0, min(1.0, float(confidence)))
            db.execute("UPDATE persona_assertions SET confidence=?, updated_at=?, last_refreshed=? WHERE id=?", (new_conf, now, now, assertion_id))
            _audit_persona(assertion_id, "edit_confidence", str(old.get("confidence", "")), str(new_conf), actor, note)
            changes.append("confidence")
        db.commit()
        return {"id": assertion_id, "updated": True, "action": "edit", "changes": changes}

    if action == "lock":
        db.execute("UPDATE persona_assertions SET locked=1, updated_at=? WHERE id=?", (now, assertion_id))
        _audit_persona(assertion_id, "lock", str(old.get("locked", 0)), "1", actor, note or "manual lock")
    elif action == "unlock":
        db.execute("UPDATE persona_assertions SET locked=0, updated_at=? WHERE id=?", (now, assertion_id))
        _audit_persona(assertion_id, "unlock", str(old.get("locked", 0)), "0", actor, note or "manual unlock")
    elif action == "delete":
        db.execute("UPDATE persona_assertions SET is_superseded=1, updated_at=? WHERE id=?", (now, assertion_id))
        _audit_persona(assertion_id, "delete", "active", "superseded", actor, note or "soft delete")
    elif action == "restore":
        db.execute("UPDATE persona_assertions SET is_superseded=0, superseded_by=NULL, updated_at=? WHERE id=?", (now, assertion_id))
        _audit_persona(assertion_id, "restore", "superseded", "active", actor, note or "restore soft deleted")
    else:
        return {"error": f"unknown action {action}"}

    db.commit()
    return {"id": assertion_id, "updated": True, "action": action}


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
