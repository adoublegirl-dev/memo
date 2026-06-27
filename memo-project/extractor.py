"""LLM 提取器 —— 从对话片段自动提取特征词、摘要、关系、冲突检测。

Phase 1 版本：增强 Prompt + 多轮对话支持 + jieba 关键词降级。
"""

import re
from typing import Any

from memo.utils.llm import llm_client
from memo.utils.logger import logger

# ── Prompt 模板 ──

_EXTRACT_SYSTEM = """你是一个精确的记忆提取引擎，为 AI Agent 的记忆系统服务。

你的任务是：从一段对话中提取结构化信息，使得这些信息可以被高效检索和关联。

核心原则：
1. **特征词要有区分度**：不要提取"我"、"这个"、"那个"等泛词。提取的是可以被未来检索锚定的概念。
2. **摘要要有信息量**：不要写"讨论了某话题"，而要写"讨论了XXX的具体方案，结论是YYY"。
3. **关系要准确**：特征词之间的关系要反映真实逻辑，不要强行关联。

输出纯 JSON，不要任何解释文字。"""

_EXTRACT_PROMPT = """从以下对话中提取记忆。

## 提取规则

### feature_tags（特征词）
提取 3-8 个最具区分度的关键词/概念，每个包含：
- name: 规范化的特征词文本（不要缩写、不要口语）
- category: 从以下选一
  - PERSON（人名）
  - OBJECT（具体物品/工具/产品）
  - LOCATION（地点）
  - EVENT（事件/会议/里程碑）
  - ORGANIZATION（公司/团队/项目）
  - CONCEPT（抽象概念/技术/方法论）

### title（标题）
10-30 字，准确概括这段对话的核心议题。

### summary（一级摘要）
≤200 字，覆盖：讨论了什么 + 结论/产出是什么 + 如果有决策，决策是什么。

### summary_detail（二级摘要）
≤800 字，补充细节：讨论过程、不同观点、具体参数、未解决问题。

### memory_type（记忆类型）
- FACT: 陈述事实或信息
- DECISION: 做出决策或达成共识
- PREFERENCE: 表达偏好或习惯
- EVENT: 记录发生的事件
- REASONING: 包含推理或分析过程

### relations（特征词关系）
从提取的特征词中选取有逻辑关联的对，每条包含：
- from: 源特征词 name
- to: 目标特征词 name
- type: CO_OCCUR（共现）/ CAUSAL（因果）/ TEMPORAL（时序）/ DERIVED（派生）

### is_update_of（可选）
如果这段对话更新/推翻了某个可能已存在的旧事实，列出旧事实的关键词。
例如：用户说"我现在用 Claude 了，不用 GPT 了" → is_update_of: ["使用GPT"]
如果不存在明确更新，不填此字段。

## 对话内容
{conversation}

请输出 JSON："""


def extract_from_conversation(
    conversation: str,
    existing_tags: list[str] | None = None,
) -> dict[str, Any]:
    """从对话中提取结构化记忆。

    Args:
        conversation: 完整对话文本（含 user/assistant 标记）
        existing_tags: 已有的特征词列表（用于上下文）

    Returns:
        {
            "title": str,
            "feature_tags": [{"name": str, "category": str}, ...],
            "summary": str,
            "summary_detail": str,
            "memory_type": str,
            "relations": [{"from": str, "to": str, "type": str}, ...],
            "is_update_of": [str, ...] | None,
        }
    """
    if not llm_client.available:
        logger.info("LLM 不可用，使用 jieba 关键词降级提取")
        return _jieba_extract(conversation)

    # 注入已有特征词上下文
    context_hint = ""
    if existing_tags:
        context_hint = f"\n\n已有的特征词库（供参考，避免重复创建）：{', '.join(existing_tags[:30])}"

    try:
        prompt = _EXTRACT_PROMPT.format(conversation=conversation[:5000] + context_hint)
        result = llm_client.chat_json(
            messages=[
                {"role": "system", "content": _EXTRACT_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=2048,
        )
        # 标准化
        result = _normalize_extraction(result)
        logger.info(
            f"LLM 提取: {len(result.get('feature_tags', []))} 特征词, "
            f"{len(result.get('relations', []))} 关系"
        )
        return result
    except Exception as e:
        logger.warning(f"LLM 提取失败 ({e})，降级为 jieba 提取")
        return _jieba_extract(conversation)


def _normalize_extraction(raw: dict) -> dict:
    """标准化 LLM 输出。"""
    result = {
        "title": str(raw.get("title", ""))[:100],
        "feature_tags": [],
        "summary": str(raw.get("summary", ""))[:500],
        "summary_detail": str(raw.get("summary_detail", ""))[:1500],
        "memory_type": raw.get("memory_type", "FACT"),
        "relations": [],
        "is_update_of": raw.get("is_update_of"),
    }

    # 标准化特征词
    for tag in raw.get("feature_tags", []):
        if isinstance(tag, str):
            result["feature_tags"].append({"name": tag, "category": "CONCEPT"})
        elif isinstance(tag, dict):
            result["feature_tags"].append({
                "name": str(tag.get("name", "")).strip(),
                "category": tag.get("category", "CONCEPT").upper(),
            })

    # 标准化关系
    for rel in raw.get("relations", []):
        if isinstance(rel, dict) and rel.get("from") and rel.get("to"):
            result["relations"].append({
                "from": str(rel["from"]).strip(),
                "to": str(rel["to"]).strip(),
                "type": rel.get("type", "CO_OCCUR").upper(),
            })

    return result


def _jieba_extract(conversation: str) -> dict:
    """无 LLM 时用 jieba 做关键词提取 + TF-IDF 排序。"""
    import jieba
    import jieba.analyse

    # 取前 2000 字符做分析
    text = conversation[:2000]

    # TF-IDF 提取 top 8 关键词，过滤泛用词
    keywords = jieba.analyse.extract_tags(text, topK=12, withWeight=True)
    _generic_words = {"User", "user", "Assistant", "assistant", "我", "你", "他", "她",
                       "这个", "那个", "什么", "怎么", "一个", "可以", "我们", "他们"}
    feature_tags = [
        {"name": kw, "category": "CONCEPT"}
        for kw, weight in keywords
        if len(kw) > 1 and weight > 0.2 and kw not in _generic_words
    ]

    # 标题：清理前缀，取第一句
    title = text.strip()
    # 去常见前缀
    for prefix in ["User: ", "user: ", "Assistant: ", "assistant: ", "Human: ", "AI: "]:
        if title.startswith(prefix):
            title = title[len(prefix):]
    for sep in ["。", "\n", ". "]:
        if sep in title:
            title = title.split(sep)[0]
            break
    title = title[:80]

    return {
        "title": title,
        "feature_tags": feature_tags[:6],
        "summary": text[:300],
        "summary_detail": text[:1500],
        "memory_type": "FACT",
        "relations": [],
        "is_update_of": None,
    }


def extract_conflicts_with_llm(
    new_summary: str,
    existing_memories: list[dict[str, str]],
) -> list[str]:
    """用 LLM 判断新记忆是否与已有记忆冲突。

    Args:
        new_summary: 新记忆摘要
        existing_memories: [{"id": str, "summary": str, "title": str}, ...]

    Returns:
        冲突的记忆 ID 列表
    """
    if not existing_memories or not llm_client.available:
        return []

    existing_text = "\n".join(
        f"- [{m['id'][:8]}] {m['title']}: {m['summary'][:200]}"
        for m in existing_memories[:5]
    )

    prompt = f"""判断以下新记忆是否与已有记忆冲突（矛盾、更新、推翻）。

新记忆：
{new_summary[:500]}

已有记忆：
{existing_text}

冲突是指：新记忆陈述的事实与旧记忆直接矛盾，例如"用户在A公司工作"变为"用户已离职去B公司"。
不是冲突：补充新信息、讨论新话题、表达不同时间点的不同状态。

输出 JSON：
{{"conflicts": ["memory_id_1", ...], "reason": "简述原因（如有冲突）"}}
如果无冲突，返回 {{"conflicts": []}}"""

    try:
        result = llm_client.chat_json(
            messages=[
                {"role": "system", "content": "你是一个事实冲突检测引擎。只输出 JSON。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=512,
        )
        return result.get("conflicts", [])
    except Exception as e:
        logger.debug(f"LLM 冲突检测失败: {e}")
        return []
