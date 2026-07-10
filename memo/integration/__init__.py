"""Hanako Agent 直接集成模块 —— 不需要 MCP，直接 import 使用。

适合在 Hanako Agent 内部直接调用 Memo，避免 MCP 通信开销。

用法:
    from memo.integration.hanako import MemoClient
    client = MemoClient()
    client.remember("今天讨论了排位赛系统...")
    results = client.recall("排位赛怎么做的？")
"""

import sys
from pathlib import Path

# 确保能导入 memo
_memo_root = Path(__file__).resolve().parent.parent.parent
if str(_memo_root) not in sys.path:
    sys.path.insert(0, str(_memo_root))

from typing import Any


class MemoClient:
    """Hanako Agent 的 Memo 记忆客户端。

    封装 engine，提供更简洁的接口。
    支持自动会话管理。
    """

    def __init__(self, agent_id: str = "hanako"):
        from memo.core.engine import engine as _engine
        self._engine = _engine
        self._agent_id = agent_id
        self._current_session_id: str | None = None
        self._engine.init()

    # ── 会话 ──

    @property
    def session_id(self) -> str:
        """获取或自动创建当前会话。"""
        if not self._current_session_id:
            self.new_session()
        return self._current_session_id

    def new_session(self, title: str = "") -> str:
        """开始新会话。"""
        session = self._engine.start_session(title=title, agent_id=self._agent_id)
        self._current_session_id = session.id
        return session.id

    def end_session(self) -> None:
        """结束当前会话。"""
        if self._current_session_id:
            self._engine.end_session(self._current_session_id)
            self._current_session_id = None

    # ── 记忆 ──

    def remember(
        self,
        content: str,
        auto_extract: bool = True,
        importance_check: bool = True,
        **kwargs,
    ) -> dict[str, Any]:
        """写入记忆。

        Args:
            content: 对话文本
            auto_extract: 是否自动提取特征词/摘要
            importance_check: 是否启用 MVG 门控（自动模式默认启用，手动「记住」时关闭）

        Returns:
            写入结果
        """
        if auto_extract:
            return self._engine.remember_conversation(
                session_id=self.session_id,
                conversation=content,
                auto_extract=True,
                skip_gating=not importance_check,
            )
        else:
            memory_id = self._engine.remember(
                session_id=self.session_id,
                raw_text=content,
                **kwargs,
            )
            return {"memory_id": memory_id}

    def recall(
        self,
        query: str,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """检索记忆。"""
        return self._engine.recall(
            query=query,
            top_k=top_k,
            current_session_id=self._current_session_id,
        )

    def stats(self) -> dict[str, Any]:
        """获取统计。"""
        return self._engine.stats()

    def maintain(self) -> dict[str, Any]:
        """手动维护。"""
        return self._engine.run_lifecycle()


# 便捷函数：在 Agent 技能中直接使用
_memo: MemoClient | None = None


def get_memo() -> MemoClient:
    """获取全局 MemoClient 单例。"""
    global _memo
    if _memo is None:
        _memo = MemoClient()
    return _memo
