"""LLM 调用包装 —— 用于记忆提取、摘要生成、关系判断。

所有 LLM 调用通过此模块，方便统一切换模型和管理成本。
"""

import json
from typing import Any

from openai import OpenAI

from memo.core.config import config
from memo.utils.logger import logger


class LLMClient:
    """OpenAI 兼容的 LLM 客户端。"""

    _instance: "LLMClient | None" = None
    _client: OpenAI | None = None

    def __new__(cls) -> "LLMClient":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @property
    def client(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI(
                api_key=config.openai_api_key,
                base_url=config.openai_base_url,
            )
        return self._client

    @property
    def available(self) -> bool:
        """LLM 是否可用（已配置 API key）。"""
        return bool(config.openai_api_key)

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 1024,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        """同步调用 LLM，返回文本。"""
        if not self.available:
            raise RuntimeError("LLM 不可用：未配置 OPENAI_API_KEY")

        kwargs: dict[str, Any] = dict(
            model=config.extraction_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if response_format:
            kwargs["response_format"] = response_format

        response = self.client.chat.completions.create(**kwargs)
        return response.choices[0].message.content or ""

    def chat_json(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> dict[str, Any]:
        """调用 LLM 并解析 JSON 返回。"""
        raw = self.chat(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            logger.warning(f"LLM 返回非 JSON: {raw[:200]}... 错误: {e}")
            # 尝试提取 JSON 块
            import re

            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                return json.loads(match.group())
            raise


# 全局单例
llm_client = LLMClient()
