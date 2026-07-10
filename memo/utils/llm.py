"""LLM 调用包装 —— 用于记忆提取、摘要生成、关系判断。

所有 LLM 调用通过此模块，方便统一切换模型和管理成本。
"""

import json
import time
from typing import Any

from openai import OpenAI, RateLimitError, APITimeoutError, APIConnectionError

from memo.core.config import config
from memo.utils.logger import logger

# ── 重试配置 ──
MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0  # 秒，指数退避：1s, 2s, 4s


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
        model: str | None = None,
    ) -> str:
        """同步调用 LLM，返回文本。支持自动重试。"""
        if not self.available:
            raise RuntimeError("LLM 不可用：未配置 OPENAI_API_KEY")

        kwargs: dict[str, Any] = dict(
            model=model or config.extraction_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if response_format:
            kwargs["response_format"] = response_format

        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                response = self.client.chat.completions.create(**kwargs)
                content = response.choices[0].message.content or ""
                if not content and attempt < MAX_RETRIES - 1:
                    # 空响应（可能是限流），重试
                    delay = RETRY_BASE_DELAY * (2 ** attempt)
                    logger.debug(f"LLM 返回空内容，{delay}s 后重试 ({attempt+1}/{MAX_RETRIES})")
                    time.sleep(delay)
                    continue
                return content
            except (RateLimitError, APITimeoutError, APIConnectionError) as e:
                last_error = e
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        f"LLM 调用失败 ({type(e).__name__})，{delay}s 后重试 ({attempt+1}/{MAX_RETRIES})"
                    )
                    time.sleep(delay)
                else:
                    raise
            except Exception as e:
                # 其他错误不重试，直接抛
                raise

        raise last_error or RuntimeError("LLM 调用失败: 空响应且重试耗尽")

    def chat_json(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 2048,
        model: str | None = None,
    ) -> dict[str, Any]:
        """调用 LLM 并解析 JSON 返回。支持重试和 JSON 修复。"""
        import re

        last_raw = ""
        for attempt in range(MAX_RETRIES):
            try:
                raw = self.chat(
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format={"type": "json_object"},
                    model=model,
                )
                last_raw = raw
                return json.loads(raw)
            except json.JSONDecodeError as e:
                # 尝试从非标准输出中提取 JSON
                match = re.search(r"\{.*\}", last_raw, re.DOTALL)
                if match:
                    try:
                        return json.loads(match.group())
                    except json.JSONDecodeError:
                        pass
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        f"LLM 返回非 JSON ({e})，{delay}s 后重试 ({attempt+1}/{MAX_RETRIES})"
                    )
                    time.sleep(delay)
                    # 重试时去掉 json_object 限制，给模型更多自由度
                    if attempt >= 1:
                        messages = list(messages)  # 不修改原列表
                        messages.append({
                            "role": "user",
                            "content": "请只输出纯 JSON，不要任何其他文字。"
                        })
                else:
                    logger.warning(f"LLM 返回非 JSON 且重试耗尽: {last_raw[:200]}...")
                    raise

        return {}


# 全局单例
llm_client = LLMClient()
