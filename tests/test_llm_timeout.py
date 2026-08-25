from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

import memo.utils.llm as llm_module


def _fresh_client():
    client = llm_module.LLMClient()
    client._client = None
    return client


def test_openai_client_has_explicit_timeout_and_no_sdk_retries(monkeypatch):
    client = _fresh_client()
    fake_openai = object()
    factory = MagicMock(return_value=fake_openai)
    monkeypatch.setattr(llm_module, "OpenAI", factory)
    monkeypatch.setattr(llm_module.config, "llm_api_key", "test-key")
    monkeypatch.setattr(llm_module.config, "llm_base_url", "https://example.invalid/v1")
    monkeypatch.setattr(llm_module.config, "llm_request_timeout_seconds", 45.0)

    assert client.client is fake_openai
    factory.assert_called_once_with(
        api_key="test-key",
        base_url="https://example.invalid/v1",
        timeout=45.0,
        max_retries=0,
    )
    client._client = None


def test_timeout_is_retried_only_once(monkeypatch):
    client = _fresh_client()
    monkeypatch.setattr(llm_module.config, "llm_api_key", "test-key")
    monkeypatch.setattr(llm_module.time, "sleep", MagicMock())

    request = httpx.Request("POST", "https://example.invalid/v1/chat/completions")
    timeout_error = llm_module.APITimeoutError(request)
    create = MagicMock(side_effect=timeout_error)
    client._client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )

    with pytest.raises(llm_module.APITimeoutError):
        client.chat([{"role": "user", "content": "test"}])

    assert create.call_count == llm_module.MAX_ATTEMPTS == 2
    llm_module.time.sleep.assert_called_once_with(1.0)
    client._client = None
