"""Anthropic Claude client implementation."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from anthropic import Anthropic, AsyncAnthropic

from backend.inference.clients.base import (
    DirectLLMClient,
    LLMResponse,
    _normalize_timeout_seconds,
    _with_default_timeout,
    get_shared_async_http_client,
    get_shared_http_client,
)
from backend.inference.providers.anthropic_ops import (
    acompletion as _anthropic_acompletion,
)
from backend.inference.providers.anthropic_ops import astream as _anthropic_astream
from backend.inference.providers.anthropic_ops import (
    completion as _anthropic_completion,
)
from backend.inference.providers.anthropic_ops import (
    extract_anthropic_tool_calls as _extract_anthropic_tool_calls_impl,
)
from backend.inference.providers.anthropic_ops import (
    map_anthropic_error as _map_anthropic_error_impl,
)
from backend.inference.providers.anthropic_ops import (
    prepare_anthropic_kwargs as _prepare_anthropic_kwargs_impl,
)


class AnthropicClient(DirectLLMClient):
    """Client for Anthropic Claude."""

    def __init__(
        self,
        model_name: str,
        api_key: str,
        timeout: float | int | None = None,
        base_url: str | None = None,
        provider_name: str = 'anthropic',
    ):
        self._model_name = model_name
        self._provider_name = provider_name
        self._request_timeout = _normalize_timeout_seconds(timeout)
        self.client = Anthropic(
            api_key=api_key,
            base_url=base_url,
            http_client=get_shared_http_client(provider_name, base_url),
        )
        self.async_client = AsyncAnthropic(
            api_key=api_key,
            base_url=base_url,
            http_client=get_shared_async_http_client(provider_name, base_url),
        )

    @staticmethod
    def _extract_anthropic_tool_calls(
        content_blocks: list,
    ) -> tuple[str, list[dict[str, Any]] | None]:
        return _extract_anthropic_tool_calls_impl(content_blocks)

    def _prepare_anthropic_kwargs(
        self, messages: list[dict[str, Any]], kwargs: dict[str, Any]
    ) -> tuple[list, dict[str, Any]]:
        return _prepare_anthropic_kwargs_impl(self, messages, kwargs)

    def _map_anthropic_error(self, exc: Exception) -> Exception:
        return _map_anthropic_error_impl(self, exc)

    def completion(self, messages: list[dict[str, Any]], **kwargs) -> LLMResponse:
        kwargs = _with_default_timeout(kwargs, self._request_timeout)
        return _anthropic_completion(self, messages, **kwargs)

    async def acompletion(
        self, messages: list[dict[str, Any]], **kwargs
    ) -> LLMResponse:
        kwargs = _with_default_timeout(kwargs, self._request_timeout)
        return await _anthropic_acompletion(self, messages, **kwargs)

    async def astream(
        self, messages: list[dict[str, Any]], **kwargs
    ) -> AsyncIterator[dict[str, Any]]:
        kwargs = _with_default_timeout(kwargs, self._request_timeout, streaming=True)
        async for chunk in _anthropic_astream(self, messages, **kwargs):
            yield chunk
