"""Tests for backend.llm.direct_clients — LLMResponse, httpx pool, get_direct_client."""

# pylint: disable=protected-access,unsubscriptable-object,invalid-overridden-method

from __future__ import annotations

import json
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest

from backend.llm.direct_clients import (
    LLMResponse,
    _pool_key,
    get_direct_client,
    get_shared_async_http_client,
    get_shared_http_client,
)


# ---------------------------------------------------------------------------
# LLMResponse
# ---------------------------------------------------------------------------
class TestLLMResponse:
    def test_basic_attributes(self):
        resp = LLMResponse(
            content="Hello!",
            model="gpt-4",
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            id="resp-123",
            finish_reason="stop",
        )
        assert resp.content == "Hello!"
        assert resp.model == "gpt-4"
        assert resp.id == "resp-123"
        assert resp.finish_reason == "stop"
        assert resp.tool_calls is None
        assert resp.usage["total_tokens"] == 15

    def test_choices_attribute(self):
        resp = LLMResponse(content="Hi", model="m", usage={}, finish_reason="length")
        assert len(resp.choices) == 1
        assert resp.choices[0].message.content == "Hi"
        assert resp.choices[0].message.role == "assistant"
        assert resp.choices[0].finish_reason == "length"

    def test_with_tool_calls(self):
        tcs = [
            {
                "id": "tc1",
                "type": "function",
                "function": {"name": "f", "arguments": "{}"},
            }
        ]
        resp = LLMResponse(content="", model="m", usage={}, tool_calls=tcs)
        assert resp.tool_calls == tcs
        # message.tool_calls are ToolCall objects wrapping the dicts
        tc_list = resp.choices[0].message.tool_calls
        assert tc_list is not None
        assert len(tc_list) == 1
        assert tc_list[0].function.name == "f"

    def test_to_dict(self):
        resp = LLMResponse(
            content="reply",
            model="gpt-4o",
            usage={"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
            id="r1",
        )
        d = resp.to_dict()
        assert d["model"] == "gpt-4o"
        assert d["id"] == "r1"
        assert d["choices"][0]["message"]["content"] == "reply"
        assert d["usage"]["total_tokens"] == 3

    def test_to_dict_with_tool_calls(self):
        tcs = [{"id": "tc1"}]
        resp = LLMResponse(content="", model="m", usage={}, tool_calls=tcs)
        d = resp.to_dict()
        tool_calls = d["choices"][0]["message"]["tool_calls"]
        assert tool_calls is not None
        assert tool_calls[0]["id"] == "tc1"
        assert tool_calls[0]["type"] == "function"

    def test_getitem(self):
        resp = LLMResponse(content="x", model="m", usage={})
        assert resp["model"] == "m"
        assert isinstance(resp["choices"], list)

    def test_response_id_kwarg(self):
        resp = LLMResponse(content="", model="m", usage={}, response_id="custom-id")
        assert resp.id == "custom-id"


# ---------------------------------------------------------------------------
# _pool_key
# ---------------------------------------------------------------------------
class TestPoolKey:
    def test_with_base_url(self):
        assert (
            _pool_key("openai", "https://api.openai.com")
            == "openai::https://api.openai.com"
        )

    def test_without_base_url(self):
        assert _pool_key("anthropic", None) == "anthropic::default"


# ---------------------------------------------------------------------------
# Shared HTTP clients (pool management)
# ---------------------------------------------------------------------------
class TestSharedHttpClients:
    def test_get_shared_sync_client(self):
        client = get_shared_http_client("test_provider_sync", "http://test")
        assert client is not None
        # Same key returns same instance
        client2 = get_shared_http_client("test_provider_sync", "http://test")
        assert client is client2

    def test_get_shared_async_client(self):
        client = get_shared_async_http_client("test_provider_async", "http://test")
        assert client is not None
        client2 = get_shared_async_http_client("test_provider_async", "http://test")
        assert client is client2


# ---------------------------------------------------------------------------
# get_direct_client factory
# ---------------------------------------------------------------------------
class TestGetDirectClient:
    def test_anthropic_model(self):
        with (
            patch("backend.llm.direct_clients.Anthropic"),
            patch("backend.llm.direct_clients.AsyncAnthropic"),
        ):
            from backend.llm.direct_clients import AnthropicClient

            client = get_direct_client("anthropic/claude-3", api_key="sk-test")
            assert isinstance(client, AnthropicClient)

    def test_claude_model_requires_explicit_provider(self):
        with pytest.raises(ValueError, match="provider"):
            get_direct_client("claude-3.5-sonnet", api_key="sk-test")

    def test_gemini_model(self):
        with patch("backend.llm.direct_clients.genai"):
            from backend.llm.direct_clients import GeminiClient

            client = get_direct_client("google/gemini-pro", api_key="key")
            assert isinstance(client, GeminiClient)

    def test_xai_grok_model(self):
        with (
            patch("backend.llm.direct_clients.OpenAI"),
            patch("backend.llm.direct_clients.AsyncOpenAI"),
        ):
            from backend.llm.direct_clients import OpenAIClient

            client = get_direct_client("xai/grok-1", api_key="key")
            assert isinstance(client, OpenAIClient)

    def test_ollama_model(self):
        with (
            patch("backend.llm.direct_clients.OpenAI"),
            patch("backend.llm.direct_clients.AsyncOpenAI"),
        ):
            from backend.llm.direct_clients import OpenAIClient

            client = get_direct_client("ollama/llama3", api_key="")
            assert isinstance(client, OpenAIClient)
            assert client._model_name == "llama3"  # prefix stripped

    def test_default_openai(self):
        with (
            patch("backend.llm.direct_clients.OpenAI"),
            patch("backend.llm.direct_clients.AsyncOpenAI"),
        ):
            from backend.llm.direct_clients import OpenAIClient

            client = get_direct_client("gpt-4o", api_key="sk-key")
            assert isinstance(client, OpenAIClient)


# ---------------------------------------------------------------------------
# AnthropicClient helpers
# ---------------------------------------------------------------------------
class TestAnthropicClientHelpers:
    def test_extract_tool_calls(self):
        from backend.llm.mappers.anthropic import extract_tool_calls

        text_block = MagicMock(type="text", text="Hello")
        tool_block = MagicMock(type="tool_use", id="tu1", input={"q": "test"})
        tool_block.name = "search"
        text, tcs = extract_tool_calls([text_block, tool_block])
        assert text == "Hello"
        assert tcs is not None
        assert len(tcs) == 1
        assert tcs[0]["function"]["name"] == "search"
        parsed_args = json.loads(tcs[0]["function"]["arguments"])
        assert parsed_args["q"] == "test"

    def test_extract_no_tool_calls(self):
        from backend.llm.mappers.anthropic import extract_tool_calls

        text_block = MagicMock(type="text", text="Just text")
        text, tcs = extract_tool_calls([text_block])
        assert text == "Just text"
        assert tcs is None

    def test_prepare_kwargs(self):
        from backend.llm.mappers.anthropic import prepare_kwargs

        messages = [
            {"role": "system", "content": "Be helpful"},
            {"role": "user", "content": "Hi"},
        ]
        filtered, kwargs = prepare_kwargs(messages, {}, default_model="claude-3")
        assert len(filtered) == 1
        assert filtered[0]["role"] == "user"
        assert kwargs["system"] == "Be helpful"
        assert kwargs["model"] == "claude-3"


# ---------------------------------------------------------------------------
# OpenAIClient helpers
# ---------------------------------------------------------------------------
class TestOpenAIClientHelpers:
    def test_extract_openai_tool_calls(self):
        from backend.llm.mappers.openai import extract_tool_calls

        tc = MagicMock()
        tc.id = "call_1"
        tc.type = "function"
        tc.function.name = "search"
        tc.function.arguments = '{"q":"test"}'
        msg = MagicMock(tool_calls=[tc])
        result = extract_tool_calls(msg)
        assert result is not None
        assert len(result) == 1
        assert result[0]["id"] == "call_1"

    def test_extract_no_tool_calls(self):
        from backend.llm.mappers.openai import extract_tool_calls

        msg = MagicMock(tool_calls=None)
        assert extract_tool_calls(msg) is None

    def test_extract_empty_tool_calls(self):
        from backend.llm.mappers.openai import extract_tool_calls

        msg = MagicMock(tool_calls=[])
        assert extract_tool_calls(msg) is None

    def test_sanitize_openai_metadata_values_to_strings(self):
        from backend.llm.direct_clients import _sanitize_openai_compatible_kwargs

        kwargs = {
            "extra_body": {
                "metadata": {
                    "session_id": "abc",
                    "trace_version": 1,
                    "tags": ["model:gpt-4", "agent:orchestrator"],
                    "extra": {"a": 1},
                }
            }
        }

        sanitized = _sanitize_openai_compatible_kwargs(kwargs)
        metadata = sanitized["extra_body"]["metadata"]
        assert metadata["session_id"] == "abc"
        assert metadata["trace_version"] == "1"
        assert metadata["tags"] == "model:gpt-4,agent:orchestrator"
        assert metadata["extra"] == '{"a":1}'


# ---------------------------------------------------------------------------
# GeminiClient helpers
# ---------------------------------------------------------------------------
class TestGeminiClientHelpers:
    def test_convert_messages(self):
        from backend.llm.mappers.gemini import convert_messages

        messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        system, gemini, _caching = convert_messages(messages)
        assert system == "System prompt"
        assert len(gemini) == 2
        assert gemini[0]["role"] == "user"
        assert gemini[1]["role"] == "model"

    def test_extract_generation_config(self):
        from backend.llm.mappers.gemini import extract_generation_config

        kwargs = {
            "model": "models/gemini-pro",
            "temperature": 0.7,
            "max_tokens": 100,
            "top_p": 0.9,
        }
        model_name, gen_cfg, _tools = extract_generation_config(kwargs)
        assert model_name == "gemini-pro"  # Strip "models/"
        assert gen_cfg["temperature"] == 0.7
        assert gen_cfg["max_output_tokens"] == 100
        assert "model" not in kwargs  # Popped

    def test_gemini_usage_none(self):
        from backend.llm.mappers.gemini import gemini_usage

        resp = MagicMock(usage_metadata=None)
        usage = gemini_usage(resp)
        assert usage["prompt_tokens"] == 0
        assert usage["total_tokens"] == 0

    def test_gemini_usage_valid(self):
        from backend.llm.mappers.gemini import gemini_usage

        meta = MagicMock(
            prompt_token_count=10, candidates_token_count=20, total_token_count=30
        )
        resp = MagicMock(usage_metadata=meta)
        usage = gemini_usage(resp)
        assert usage["prompt_tokens"] == 10
        assert usage["completion_tokens"] == 20
        assert usage["total_tokens"] == 30

    def test_extract_gemini_tool_calls(self):
        from backend.llm.mappers.gemini import extract_tool_calls

        fc = MagicMock()
        fc.name = "search"
        fc.args = {"q": "hello"}
        part = MagicMock(function_call=fc)
        candidate = MagicMock()
        candidate.content = {"parts": [part]}
        resp = MagicMock(candidates=[candidate])
        tcs = extract_tool_calls(resp)
        assert tcs is not None
        assert len(tcs) == 1
        assert tcs[0]["function"]["name"] == "search"

    def test_extract_gemini_no_tool_calls(self):
        from backend.llm.mappers.gemini import extract_tool_calls

        part = MagicMock(function_call=None)
        candidate = MagicMock()
        candidate.content = {"parts": [part]}
        resp = MagicMock(candidates=[candidate])
        assert extract_tool_calls(resp) is None

    def test_extract_gemini_finish_reason_from_dict_shape(self):
        from backend.llm.mappers.gemini import extract_finish_reason

        response = {
            "candidates": [
                {
                    "finishReason": "SAFETY",
                    "content": {"parts": []},
                }
            ]
        }
        assert extract_finish_reason(response) == "SAFETY"

    def test_extract_gemini_block_reason_from_prompt_feedback(self):
        from backend.llm.mappers.gemini import extract_block_reason

        response = {
            "promptFeedback": {
                "blockReason": "SAFETY",
            }
        }
        assert extract_block_reason(response) == "SAFETY"

    def test_ensure_non_empty_gemini_content_synthesizes_for_empty_response(self):
        from backend.llm.mappers.gemini import ensure_non_empty_content

        response = {
            "candidates": [{"finishReason": "SAFETY", "content": {"parts": []}}],
            "promptFeedback": {"blockReason": "SAFETY"},
        }
        content = ensure_non_empty_content(
            response,
            content="",
            tool_calls=None,
        )

        assert "blocked by safety" in content.lower()

    def test_ensure_non_empty_gemini_content_keeps_text_when_present(self):
        from backend.llm.mappers.gemini import ensure_non_empty_content

        content = ensure_non_empty_content(
            response={},
            content="hello",
            tool_calls=None,
        )
        assert content == "hello"

    def test_ensure_non_empty_gemini_content_keeps_empty_for_tool_calls(self):
        from backend.llm.mappers.gemini import ensure_non_empty_content

        content = ensure_non_empty_content(
            response={},
            content="",
            tool_calls=[
                {
                    "id": "tc1",
                    "type": "function",
                    "function": {"name": "x", "arguments": "{}"},
                }
            ],
        )
        assert content == ""


# ---------------------------------------------------------------------------
# DirectLLMClient.model_name property
# ---------------------------------------------------------------------------
class TestDirectLLMClientModelName:
    def test_model_name_not_set(self):
        from backend.llm.direct_clients import DirectLLMClient

        class TestClient(DirectLLMClient):
            def completion(self, messages, **kwargs):
                pass

            async def acompletion(self, messages, **kwargs):
                pass

            async def astream(self, messages, **kwargs):
                yield {}

        c = TestClient()
        with pytest.raises(NotImplementedError):
            _ = c.model_name

    def test_model_name_set(self):
        with (
            patch("backend.llm.direct_clients.OpenAI"),
            patch("backend.llm.direct_clients.AsyncOpenAI"),
        ):
            from backend.llm.direct_clients import OpenAIClient

            c = OpenAIClient("gpt-4", "key")
            assert c.model_name == "gpt-4"
