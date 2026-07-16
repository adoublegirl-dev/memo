"""文本归一化与结构化动作指纹。"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime

_MOOD_RE = re.compile(r"<mood>.*?</mood>", re.DOTALL | re.IGNORECASE)
_ID_RE = re.compile(r"\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b", re.IGNORECASE)
_SHORT_ID_RE = re.compile(r"`?[0-9a-f]{8}\.\.\.?`?", re.IGNORECASE)
_WS_RE = re.compile(r"\s+")
_DATE_RE = re.compile(r"(20\d{2})[年/\-.](\d{1,2})[月/\-.](\d{1,2})日?")

_BOILERPLATE_PATTERNS = [
    r"提取方式[:：]\s*\w+",
    r"冲突[:：]\s*\d+\s*条",
    r"ID[:：]\s*`?[0-9a-f\-]{8,}`?",
    r"状态[:：]\s*(doing|todo|done|进行中|已完成)",
]

_ACTION_PATTERNS = [
    ("todo_add", re.compile(r"(添加|创建|新增|加一条).{0,12}(测试)?待办|todo_add", re.I)),
    ("todo_close", re.compile(r"(完成|关闭|办结).{0,12}待办|todo_close", re.I)),
    ("todo_update", re.compile(r"(更新|修改|编辑).{0,12}待办|todo_update", re.I)),
    ("space_create", re.compile(r"(创建|新增).{0,12}(space|空间)|space_create", re.I)),
    ("space_activate", re.compile(r"(激活|切换).{0,12}(space|空间)|space_activate", re.I)),
    ("memory_govern", re.compile(r"(标记|置顶|删除|恢复).{0,12}记忆|memory_govern", re.I)),
]

_TEST_OR_OP_RE = re.compile(
    r"(测试|创建成功|添加成功|已添加|拉取完成|构建通过|验证通过|npm run build|test\.bat|git pull|git push)",
    re.I,
)

_PERSONA_HINT_RE = re.compile(
    r"(偏好|习惯|价值观|反感|喜欢|倾向|决定|决策|沟通风格|审美|工作方式|适合|情绪|敏感|底线|认为)",
    re.I,
)


def _normalize_dates(text: str) -> str:
    def repl(m: re.Match) -> str:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return datetime(y, mo, d).strftime("%Y-%m-%d")
        except ValueError:
            return m.group(0)
    return _DATE_RE.sub(repl, text)


def normalize_conversation(text: str) -> str:
    """用于去重的保守归一化。"""
    if not text:
        return ""
    s = _MOOD_RE.sub(" ", text)
    s = _normalize_dates(s)
    s = _ID_RE.sub("<id>", s)
    s = _SHORT_ID_RE.sub("<id>", s)
    for pattern in _BOILERPLATE_PATTERNS:
        s = re.sub(pattern, " ", s, flags=re.I)
    s = s.replace("\r", "\n")
    s = re.sub(r"[`*_#>\-]+", " ", s)
    s = re.sub(r"[，。！？；：、,.!?;:()（）\[\]【】\"'“”‘’]+", " ", s)
    s = _WS_RE.sub(" ", s).strip().lower()
    return s


def stable_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compact_key(text: str, limit: int = 120) -> str:
    normalized = normalize_conversation(text)
    return stable_hash(normalized[:limit]) if normalized else ""


def structured_action_key(text: str, title: str = "", summary: str = "") -> tuple[str, str, str]:
    """返回 action_key/entity_key/fact_key。

    entity_key 以显式 UUID、待办标题、Space 名称等可识别实体为优先；当前先做保守规则。
    """
    joined = "\n".join([title or "", summary or "", text or ""])
    normalized = normalize_conversation(joined)
    action = ""
    for name, pattern in _ACTION_PATTERNS:
        if pattern.search(joined):
            action = name
            break

    entity = ""
    id_match = _ID_RE.search(joined)
    if id_match:
        entity = id_match.group(0).lower()
    elif action.startswith("todo"):
        # 尽量提取中文引号里的待办标题，否则取归一化前 80 字。
        title_match = re.search(r"[“\"]([^”\"]{3,80})[”\"]", joined)
        entity = normalize_conversation(title_match.group(1)) if title_match else normalized[:80]
    elif action.startswith("space"):
        title_match = re.search(r"(?:空间|space)[：: ]*([\w\u4e00-\u9fff\- ]{2,60})", joined, re.I)
        entity = normalize_conversation(title_match.group(1)) if title_match else normalized[:80]

    action_key = f"{action}:{stable_hash(entity)[:16]}" if action and entity else ""
    fact_key = f"{action}:{stable_hash(normalized[:160])[:16]}" if action else stable_hash(normalized[:180])[:16]
    return action_key, entity, fact_key


def is_structured_operational(text: str, title: str = "", summary: str = "") -> bool:
    joined = "\n".join([title or "", summary or "", text or ""])
    action_key, _, _ = structured_action_key(joined)
    return bool(action_key) or bool(_TEST_OR_OP_RE.search(joined))


def is_persona_relevant(text: str, title: str = "", summary: str = "", memory_type: str = "", signal_level: int = 0) -> bool:
    joined = "\n".join([title or "", summary or "", text or ""])
    mt = str(memory_type or "").upper()
    if mt in {"PREFERENCE", "DECISION", "REASONING"}:
        return True
    if mt == "EVENT" and signal_level <= 0 and is_structured_operational(joined):
        return False
    return bool(_PERSONA_HINT_RE.search(joined))
