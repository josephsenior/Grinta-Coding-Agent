"""OpenAI and OpenAI-compatible client implementations."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any

from openai import AsyncOpenAI, OpenAI

from backend.inference.clients.base import (
    DirectLLMClient,
    LLMResponse,
    TransportProfile,
    _normalize_timeout_seconds,
    _with_default_timeout,
    get_shared_async_http_client,
    get_shared_http_client,
)
from backend.inference.providers.openai_ops import (
    acompletion as _openai_acompletion,
)
from backend.inference.providers.openai_ops import astream as _openai_astream
from backend.inference.providers.openai_ops import (
    clean_messages as _clean_messages_impl,
)
from backend.inference.providers.openai_ops import completion as _openai_completion
from backend.inference.providers.openai_ops import (
    extract_openai_tool_calls as _extract_openai_tool_calls_impl,
)
from backend.inference.providers.openai_ops import (
    map_openai_error as _map_openai_error_impl,
)
from backend.inference.providers.openai_ops import (
    strip_unsupported_params as _strip_unsupported_params_impl,
)


class OpenAIClient(DirectLLMClient):
    """Client for OpenAI and OpenAI-compatible APIs (like xAI Grok)."""

    def __init__(
        self,
        model_name: str,
        api_key: str,
        base_url: str | None = None,
        profile: TransportProfile | None = None,
        timeout: float | int | None = None,
        provider_name: str = 'openai',
    ):
        self._model_name = model_name
        self._api_base_url = base_url
        self._profile = profile or TransportProfile()
        self._provider_name = provider_name
        self._request_timeout = _normalize_timeout_seconds(timeout)
        effective_api_key = api_key or os.environ.get('OPENAI_API_KEY') or 'ollama'
        self.client = OpenAI(
            api_key=effective_api_key,
            base_url=base_url,
            http_client=get_shared_http_client(provider_name, base_url),
        )
        self.async_client = AsyncOpenAI(
            api_key=effective_api_key,
            base_url=base_url,
            http_client=get_shared_async_http_client(provider_name, base_url),
        )

    @staticmethod
    def _extract_openai_tool_calls(message: Any) -> list[dict[str, Any]] | None:
        return _extract_openai_tool_calls_impl(message)

    def _map_openai_error(self, exc: Exception) -> Exception:
        return _map_openai_error_impl(self, exc)

    def _strip_unsupported_params(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        return _strip_unsupported_params_impl(self._profile, kwargs)

    def _clean_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return _clean_messages_impl(self._profile, messages)

    def completion(self, messages: list[dict[str, Any]], **kwargs) -> LLMResponse:
        kwargs = _with_default_timeout(kwargs, self._request_timeout)
        return _openai_completion(self, messages, **kwargs)

    async def acompletion(
        self, messages: list[dict[str, Any]], **kwargs
    ) -> LLMResponse:
        kwargs = _with_default_timeout(kwargs, self._request_timeout)
        return await _openai_acompletion(self, messages, **kwargs)

    async def astream(
        self, messages: list[dict[str, Any]], **kwargs
    ) -> AsyncIterator[dict[str, Any]]:
        kwargs = _with_default_timeout(kwargs, self._request_timeout, streaming=True)
        async for chunk in _openai_astream(self, messages, **kwargs):
            yield chunk


class OpenCodeResponsesClient(OpenAIClient):
    """OpenCode Zen models served via OpenAI Responses API (/responses)."""

    def completion(self, messages: list[dict[str, Any]], **kwargs) -> LLMResponse:
        from backend.inference.providers.opencode_responses_ops import (
            completion as responses_completion,
        )

        return responses_completion(self, messages, **kwargs)

    async def acompletion(
        self, messages: list[dict[str, Any]], **kwargs
    ) -> LLMResponse:
        from backend.inference.providers.opencode_responses_ops import (
            acompletion as responses_acompletion,
        )

        return await responses_acompletion(self, messages, **kwargs)

    async def astream(
        self, messages: list[dict[str, Any]], **kwargs
    ) -> AsyncIterator[dict[str, Any]]:
        from backend.inference.providers.opencode_responses_ops import (
            astream as responses_astream,
        )

        async for chunk in responses_astream(self, messages, **kwargs):
            yield chunk
