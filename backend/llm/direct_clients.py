"""Direct LLM clients for OpenAI, Anthropic, Google Gemini, and xAI Grok.

This module provides direct SDK integrations with major LLM providers,
offering a lightweight and stable alternative to multi-provider abstraction libraries.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any, cast

from google import genai
import httpx
from anthropic import Anthropic, AsyncAnthropic
from openai import AsyncOpenAI, OpenAI

from backend.core.logger import forge_logger as logger

# ---------------------------------------------------------------------------
# Shared httpx connection pool
# ---------------------------------------------------------------------------
# LLM SDKs (OpenAI, Anthropic) use httpx internally. By default each SDK
# client creates its own transport, wasting TCP connections when many
# sessions hit the same provider.  We share httpx.Client / AsyncClient
# instances keyed by (provider, base_url) so keep-alive connections are
# reused across sessions.
# ---------------------------------------------------------------------------

_POOL_LIMITS = httpx.Limits(
    max_connections=20,
    max_keepalive_connections=10,
    keepalive_expiry=120,
)

_shared_sync_clients: dict[str, httpx.Client] = {}
_shared_async_clients: dict[str, httpx.AsyncClient] = {}
_pool_lock = threading.Lock()


def _pool_key(provider: str, base_url: str | None) -> str:
    """Deterministic cache key for a provider + base_url pair."""
    return f"{provider}::{base_url or 'default'}"


def get_shared_http_client(provider: str, base_url: str | None = None) -> httpx.Client:
    """Return a shared *sync* httpx.Client for the given provider."""
    key = _pool_key(provider, base_url)
    if key not in _shared_sync_clients:
        with _pool_lock:
            if key not in _shared_sync_clients:
                _shared_sync_clients[key] = httpx.Client(
                    limits=_POOL_LIMITS,
                    timeout=httpx.Timeout(timeout=600.0, connect=10.0),
                    follow_redirects=True,
                )
                logger.debug("Created shared sync httpx pool for %s", key)
    return _shared_sync_clients[key]


def get_shared_async_http_client(
    provider: str, base_url: str | None = None
) -> httpx.AsyncClient:
    """Return a shared *async* httpx.AsyncClient for the given provider."""
    key = _pool_key(provider, base_url)
    if key not in _shared_async_clients:
        with _pool_lock:
            if key not in _shared_async_clients:
                _shared_async_clients[key] = httpx.AsyncClient(
                    limits=_POOL_LIMITS,
                    timeout=httpx.Timeout(timeout=600.0, connect=10.0),
                    follow_redirects=True,
                )
                logger.debug("Created shared async httpx pool for %s", key)
    return _shared_async_clients[key]


class LLMResponse:
    """Standardized response object for LLM calls with attribute and dict access."""

    def __init__(
        self,
        content: str,
        model: str,
        usage: dict[str, int],
        response_id: str = "",
        finish_reason: str = "stop",
        tool_calls: list[dict[str, Any]] | None = None,
        **kwargs,
    ):
        self.content = content
        self.model = model
        self.usage = usage
        self.id = kwargs.get("response_id", kwargs.get("id", response_id))
        self.finish_reason = finish_reason
        self.tool_calls = tool_calls

        # Build nested structure for attribute-style access
        class ToolCallFunction:
            def __init__(self, name: str, arguments: str):
                self.name = name
                self.arguments = arguments
            
            def model_dump(self):
                return {"name": self.name, "arguments": self.arguments}

        class ToolCall:
            def __init__(self, tc_dict: dict[str, Any]):
                self.id = tc_dict.get("id")
                self.type = tc_dict.get("type")
                func_dict = tc_dict.get("function", {})
                self.function = ToolCallFunction(
                    name=func_dict.get("name", ""),
                    arguments=func_dict.get("arguments", "{}"),
                )
                # Support any other fields via setattr to be safe
                for k, v in tc_dict.items():
                    if k not in ["id", "type", "function"]:
                        setattr(self, k, v)
            
            def model_dump(self):
                return {
                    "id": self.id,
                    "type": self.type,
                    "function": self.function.model_dump()
                }

        class Message:
            def __init__(self, content, role, tool_calls_dict=None):
                self.content = content
                self.role = role
                self.tool_calls = (
                    [ToolCall(tc) for tc in tool_calls_dict]
                    if tool_calls_dict
                    else None
                )

        class Choice:
            def __init__(self, content, role, finish_reason, tool_calls_dict=None):
                self.message = Message(content, role, tool_calls_dict)
                self.finish_reason = finish_reason

        self.choices = [Choice(content, "assistant", finish_reason, tool_calls)]

    def to_dict(self) -> dict[str, Any]:
        message: dict[str, Any] = {"content": self.content, "role": "assistant"}
        if self.tool_calls:
            message["tool_calls"] = self.tool_calls  # type: ignore[assignment]

        return {
            "choices": [{"message": message, "finish_reason": self.finish_reason}],
            "usage": self.usage,
            "id": self.id,
            "model": self.model,
        }

    def __getitem__(self, key):
        """Allow dict-like access to the underlying dict representation."""
        return self.to_dict()[key]


class DirectLLMClient(ABC):
    """Abstract base class for direct LLM clients."""

    _model_name: str = ""

    @abstractmethod
    def completion(self, messages: list[dict[str, Any]], **kwargs) -> LLMResponse:
        pass

    @abstractmethod
    async def acompletion(
        self, messages: list[dict[str, Any]], **kwargs
    ) -> LLMResponse:
        pass

    @abstractmethod
    def astream(
        self, messages: list[dict[str, Any]], **kwargs
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream responses asynchronously. Returns an async iterator."""
        pass

    def __init_subclass__(cls, **kwargs):
        """Ensure subclasses define model_name attribute."""
        super().__init_subclass__(**kwargs)

    @property
    def model_name(self) -> str:
        """Get the model name. Must be implemented by subclasses."""
        if not self._model_name:
            raise NotImplementedError("Subclasses must set _model_name attribute")
        return self._model_name

    def get_completion_cost(
        self, prompt_tokens: int, completion_tokens: int, config: Any | None = None
    ) -> float:
        """Calculate completion cost for this client's model."""
        from backend.llm.cost_tracker import get_completion_cost

        return get_completion_cost(
            self.model_name, prompt_tokens, completion_tokens, config
        )


class OpenAIClient(DirectLLMClient):
    """Client for OpenAI and OpenAI-compatible APIs (like xAI Grok)."""

    def __init__(self, model_name: str, api_key: str, base_url: str | None = None):
        self._model_name = model_name
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            http_client=get_shared_http_client("openai", base_url),
        )
        self.async_client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            http_client=get_shared_async_http_client("openai", base_url),
        )

    @staticmethod
    def _extract_openai_tool_calls(message: Any) -> list[dict[str, Any]] | None:
        from backend.llm.mappers.openai import extract_tool_calls

        return extract_tool_calls(message)

    def _map_openai_error(self, exc: Exception) -> Exception:
        """Map openai SDK exceptions to Forge LLM exceptions."""
        import openai
        from backend.llm.exceptions import (
            RateLimitError,
            AuthenticationError,
            BadRequestError,
            ContextWindowExceededError,
            NotFoundError,
            APIConnectionError,
            InternalServerError,
            Timeout,
            APIError as ForgeAPIError,
            is_context_window_error,
        )

        if isinstance(exc, (openai.APITimeoutError, httpx.TimeoutException)):
            return Timeout(str(exc), llm_provider="openai", model=self.model_name)
        if isinstance(exc, (openai.APIConnectionError, httpx.RequestError)):
            return APIConnectionError(str(exc), llm_provider="openai", model=self.model_name)
        if isinstance(exc, openai.RateLimitError):
            return RateLimitError(str(exc), llm_provider="openai", model=self.model_name)
        if isinstance(exc, openai.AuthenticationError):
            return AuthenticationError(str(exc), llm_provider="openai", model=self.model_name)
        if isinstance(exc, openai.BadRequestError):
            error_str = str(exc).lower()
            if is_context_window_error(error_str, exc):
                return ContextWindowExceededError(str(exc), llm_provider="openai", model=self.model_name)
            return BadRequestError(str(exc), llm_provider="openai", model=self.model_name)
        if isinstance(exc, openai.NotFoundError):
            return NotFoundError(str(exc), llm_provider="openai", model=self.model_name)
        if isinstance(exc, openai.InternalServerError):
            return InternalServerError(str(exc), llm_provider="openai", model=self.model_name)
        if isinstance(exc, openai.APIStatusError):
            return ForgeAPIError(
                str(exc),
                llm_provider="openai",
                model=self.model_name,
                status_code=exc.status_code,
            )
        return exc

    def completion(self, messages: list[dict[str, Any]], **kwargs) -> LLMResponse:
        if "model" not in kwargs:
            kwargs["model"] = self.model_name
        try:
            response = self.client.chat.completions.create(
                messages=messages,  # type: ignore[arg-type]
                **kwargs,
            )
        except Exception as e:
            raise self._map_openai_error(e) from e
        if not getattr(response, "choices", None) or len(response.choices) == 0:
            from backend.llm.exceptions import BadRequestError
            raise BadRequestError(
                "OpenAI completion returned no choices",
                llm_provider="openai",
                model=self.model_name,
            )
        first = response.choices[0]
        msg = first.message
        tool_calls = self._extract_openai_tool_calls(msg)
        return LLMResponse(
            content=msg.content or "",
            model=response.model,
            usage={
                "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                "completion_tokens": response.usage.completion_tokens
                if response.usage
                else 0,
                "total_tokens": response.usage.total_tokens if response.usage else 0,
            },
            id=response.id,
            finish_reason=getattr(first, "finish_reason", None) or "",
            tool_calls=tool_calls,
        )

    async def acompletion(
        self, messages: list[dict[str, Any]], **kwargs
    ) -> LLMResponse:
        model = kwargs.pop("model", self.model_name)
        try:
            response = await self.async_client.chat.completions.create(
                model=model,
                messages=messages,  # type: ignore[arg-type]
                **kwargs,
            )
        except Exception as e:
            raise self._map_openai_error(e) from e
        if not getattr(response, "choices", None) or len(response.choices) == 0:
            from backend.llm.exceptions import BadRequestError
            raise BadRequestError(
                "OpenAI completion returned no choices",
                llm_provider="openai",
                model=self.model_name,
            )
        first = response.choices[0]
        msg = first.message
        tool_calls = self._extract_openai_tool_calls(msg)
        return LLMResponse(
            content=msg.content or "",
            model=response.model,
            usage={
                "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                "completion_tokens": response.usage.completion_tokens
                if response.usage
                else 0,
                "total_tokens": response.usage.total_tokens if response.usage else 0,
            },
            id=response.id,
            finish_reason=getattr(first, "finish_reason", None) or "",
            tool_calls=tool_calls,
        )

    async def astream(
        self, messages: list[dict[str, Any]], **kwargs
    ) -> AsyncIterator[dict[str, Any]]:
        kwargs["stream"] = True
        model = kwargs.pop("model", self.model_name)
        try:
            stream = await self.async_client.chat.completions.create(
                model=model,
                messages=messages,  # type: ignore[arg-type]
                **kwargs,
            )
        except Exception as e:
            raise self._map_openai_error(e) from e
        try:
            async for chunk in stream:  # type: ignore[attr-defined]
                yield chunk.model_dump()
        except Exception as e:
            raise self._map_openai_error(e) from e


class AnthropicClient(DirectLLMClient):
    """Client for Anthropic Claude."""

    def __init__(self, model_name: str, api_key: str):
        self._model_name = model_name
        self.client = Anthropic(
            api_key=api_key,
            http_client=get_shared_http_client("anthropic"),
        )
        self.async_client = AsyncAnthropic(
            api_key=api_key,
            http_client=get_shared_async_http_client("anthropic"),
        )

    @staticmethod
    def _extract_anthropic_tool_calls(
        content_blocks: list,
    ) -> tuple[str, list[dict[str, Any]] | None]:
        from backend.llm.mappers.anthropic import extract_tool_calls

        return extract_tool_calls(content_blocks)

    def _prepare_anthropic_kwargs(
        self, messages: list[dict[str, Any]], kwargs: dict[str, Any]
    ) -> tuple[list, dict[str, Any]]:
        from backend.llm.mappers.anthropic import prepare_kwargs

        return prepare_kwargs(messages, kwargs, self.model_name)

    def _map_anthropic_error(self, exc: Exception) -> Exception:
        """Map anthropic SDK exceptions to Forge LLM exceptions."""
        import anthropic
        from backend.llm.exceptions import (
            RateLimitError,
            AuthenticationError,
            BadRequestError,
            ContextWindowExceededError,
            NotFoundError,
            APIConnectionError,
            InternalServerError,
            Timeout,
            APIError as ForgeAPIError,
            is_context_window_error,
        )

        if isinstance(exc, (anthropic.APITimeoutError, httpx.TimeoutException)):
            return Timeout(str(exc), llm_provider="anthropic", model=self.model_name)
        if isinstance(exc, (anthropic.APIConnectionError, httpx.RequestError)):
            return APIConnectionError(str(exc), llm_provider="anthropic", model=self.model_name)
        if isinstance(exc, anthropic.RateLimitError):
            return RateLimitError(str(exc), llm_provider="anthropic", model=self.model_name)
        if isinstance(exc, anthropic.AuthenticationError):
            return AuthenticationError(str(exc), llm_provider="anthropic", model=self.model_name)
        if isinstance(exc, anthropic.BadRequestError):
            error_str = str(exc).lower()
            if is_context_window_error(error_str, exc):
                return ContextWindowExceededError(str(exc), llm_provider="anthropic", model=self.model_name)
            return BadRequestError(str(exc), llm_provider="anthropic", model=self.model_name)
        if isinstance(exc, anthropic.NotFoundError):
            return NotFoundError(str(exc), llm_provider="anthropic", model=self.model_name)
        if isinstance(exc, anthropic.InternalServerError):
            return InternalServerError(str(exc), llm_provider="anthropic", model=self.model_name)
        if isinstance(exc, anthropic.APIStatusError):
            return ForgeAPIError(
                str(exc),
                llm_provider="anthropic",
                model=self.model_name,
                status_code=exc.status_code,
            )
        return exc

    def completion(self, messages: list[dict[str, Any]], **kwargs) -> LLMResponse:
        filtered, kwargs = self._prepare_anthropic_kwargs(messages, kwargs)
        model = kwargs.pop("model", self.model_name)
        try:
            response = self.client.messages.create(
                model=model,
                messages=filtered,  # type: ignore[arg-type]
                **kwargs,
            )
        except Exception as e:
            raise self._map_anthropic_error(e) from e
        content, tool_calls = self._extract_anthropic_tool_calls(response.content)
        return LLMResponse(
            content=content,
            model=response.model,
            usage={
                "prompt_tokens": response.usage.input_tokens,
                "completion_tokens": response.usage.output_tokens,
                "total_tokens": response.usage.input_tokens
                + response.usage.output_tokens,
            },
            id=response.id,
            finish_reason=response.stop_reason or "stop",
            tool_calls=tool_calls,
        )

    async def acompletion(
        self, messages: list[dict[str, Any]], **kwargs
    ) -> LLMResponse:
        filtered, kwargs = self._prepare_anthropic_kwargs(messages, kwargs)
        model = kwargs.pop("model", self.model_name)
        try:
            response = await self.async_client.messages.create(
                model=model,
                messages=filtered,  # type: ignore[arg-type]
                **kwargs,
            )
        except Exception as e:
            raise self._map_anthropic_error(e) from e
        content, tool_calls = self._extract_anthropic_tool_calls(response.content)
        return LLMResponse(
            content=content,
            model=response.model,
            usage={
                "prompt_tokens": response.usage.input_tokens,
                "completion_tokens": response.usage.output_tokens,
                "total_tokens": response.usage.input_tokens
                + response.usage.output_tokens,
            },
            id=response.id,
            finish_reason=response.stop_reason or "stop",
            tool_calls=tool_calls,
        )

    async def astream(
        self, messages: list[dict[str, Any]], **kwargs
    ) -> AsyncIterator[dict[str, Any]]:
        system_msg = next(
            (m["content"] for m in messages if m["role"] == "system"), None
        )
        filtered_messages = [m for m in messages if m["role"] != "system"]

        if "model" not in kwargs:
            kwargs["model"] = self.model_name

        try:
            async with self.async_client.messages.stream(
                messages=filtered_messages,  # type: ignore[arg-type]
                system=system_msg,  # type: ignore[arg-type]
                **kwargs,
            ) as stream:
                async for event in stream:
                    # Convert Anthropic events to OpenAI-like chunks for compatibility
                    if event.type == "content_block_start" and event.content_block.type == "tool_use":
                        yield {
                            "choices": [{
                                "delta": {
                                    "tool_calls": [{
                                        "index": event.index,
                                        "id": event.content_block.id,
                                        "type": "function",
                                        "function": {
                                            "name": event.content_block.name,
                                            "arguments": ""
                                        }
                                    }]
                                },
                                "finish_reason": None
                            }]
                        }
                    elif event.type == "content_block_delta" and event.delta.type == "input_json_delta":
                        yield {
                            "choices": [{
                                "delta": {
                                    "tool_calls": [{
                                        "index": event.index,
                                        "function": {"arguments": getattr(event.delta, "partial_json", "")}
                                    }]
                                },
                                "finish_reason": None
                            }]
                        }
                    elif event.type == "content_block_delta":
                        yield {
                            "choices": [
                                {
                                    "delta": {"content": getattr(event.delta, "text", "")},  # type: ignore[union-attr]
                                    "finish_reason": None,
                                }
                            ]
                        }
                    elif event.type == "message_stop":
                        yield {"choices": [{"delta": {}, "finish_reason": "stop"}]}
        except Exception as e:
            raise self._map_anthropic_error(e) from e


class GeminiClient(DirectLLMClient):
    """Client for Google Gemini."""

    def __init__(self, model_name: str, api_key: str):
        self._model_name = model_name
        self.api_key = api_key
        
        # Add timeout to prevent infinite hanging when the API is overloaded
        from google.genai.types import HttpOptions
        http_options = HttpOptions(timeout=120000) # 2 minutes
        self.client = genai.Client(api_key=api_key, http_options=http_options)

    def _resolve_gemini_model_name(self, model_name: str | None) -> str:
        """Normalize model name for Gemini API."""
        name = model_name or self.model_name
        return name.split("/")[-1] if "/" in name else name

    def _get_gemini_cache_name(
        self,
        caching_requested: bool,
        model_name: str,
        system_instruction: str | None,
        history_messages: list,
    ) -> str | None:
        """Get cache name if caching requested and there is content to cache."""
        if not caching_requested:
            return None
        from backend.llm.gemini_cache import gemini_cache_manager

        history_to_cache = history_messages if history_messages else []
        if not history_to_cache and not system_instruction:
            return None
        return gemini_cache_manager.get_or_create_cache(
            client=self.client,
            model=model_name,
            system_instruction=system_instruction,
            messages=history_to_cache,
        )

    def _extract_gemini_text(self, message: dict[str, Any]) -> str:
        parts = message.get("parts") or []
        text_parts: list[str] = []
        for part in parts:
            if isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str) and text:
                    text_parts.append(text)
        return "\n".join(text_parts)

    def _split_gemini_history_and_prompt(
        self, gemini_messages: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], str]:
        if not gemini_messages:
            return [], ""

        active_messages = list(gemini_messages)
        while active_messages and active_messages[-1].get("role") != "user":
            active_messages.pop()

        if not active_messages:
            logger.warning(
                "GeminiClient: no trailing user message found; falling back to last message text"
            )
            fallback_prompt = self._extract_gemini_text(gemini_messages[-1])
            fallback_history = gemini_messages[:-1] if len(gemini_messages) > 1 else []
            return fallback_history, fallback_prompt

        prompt_start = len(active_messages) - 1
        while prompt_start > 0 and active_messages[prompt_start - 1].get("role") == "user":
            prompt_start -= 1

        history = active_messages[:prompt_start]
        prompt = "\n".join(
            text
            for text in (
                self._extract_gemini_text(message)
                for message in active_messages[prompt_start:]
            )
            if text
        )
        return history, prompt

    def _build_gemini_chat(
        self, messages: list[dict[str, Any]], kwargs: dict[str, Any]
    ) -> tuple[
        str, dict[str, Any], str | None, list[dict], str, list | None, str | None
    ]:
        """Shared setup for Gemini completion / acompletion / astream."""
        from backend.llm.mappers.gemini import (
            extract_generation_config,
            convert_messages,
        )

        model_name_raw, gen_cfg, tools = extract_generation_config(kwargs)
        model_name = self._resolve_gemini_model_name(model_name_raw)

        system_instruction, gemini_messages, caching_requested = convert_messages(
            messages
        )

        history, prompt = self._split_gemini_history_and_prompt(gemini_messages)

        cache_name = self._get_gemini_cache_name(
            caching_requested, model_name, system_instruction, history
        )
        return (
            model_name,
            gen_cfg,
            system_instruction,
            history,
            prompt,
            tools,
            cache_name,
        )

    def _map_gemini_error(self, exc: Exception) -> Exception:
        """Map google.genai exceptions to Forge LLM exceptions."""
        from google.genai.errors import APIError
        from backend.llm.exceptions import (
            RateLimitError,
            AuthenticationError,
            BadRequestError,
            ContextWindowExceededError,
            NotFoundError,
            InternalServerError,
            ServiceUnavailableError,
            Timeout,
            APIConnectionError,
            APIError as ForgeAPIError,
            is_context_window_error,
        )
        import asyncio
        import aiohttp

        if isinstance(exc, (asyncio.TimeoutError, httpx.TimeoutException)):
            return Timeout(str(exc), llm_provider="google", model=self.model_name)
        if isinstance(exc, (aiohttp.ClientError, httpx.RequestError)):
            return APIConnectionError(str(exc), llm_provider="google", model=self.model_name)

        if isinstance(exc, APIError):
            error_str = str(exc).lower()
            if exc.code == 429 or "quota" in error_str or "rate limit" in error_str:
                return RateLimitError(str(exc), llm_provider="google", model=self.model_name)
            if exc.code == 401 or "unauthorized" in error_str or "invalid api key" in error_str:
                return AuthenticationError(str(exc), llm_provider="google", model=self.model_name)
            if exc.code == 404 or "not found" in error_str:
                return NotFoundError(str(exc), llm_provider="google", model=self.model_name)
            if exc.code in (500, 502, 503, 504) or "unavailable" in error_str or "overloaded" in error_str:
                return ServiceUnavailableError(str(exc), llm_provider="google", model=self.model_name)
            if exc.code == 400:
                if is_context_window_error(error_str, exc):
                    return ContextWindowExceededError(str(exc), llm_provider="google", model=self.model_name)
                return BadRequestError(str(exc), llm_provider="google", model=self.model_name)
            if exc.code and exc.code >= 500:
                return InternalServerError(str(exc), llm_provider="google", model=self.model_name)
            return ForgeAPIError(str(exc), llm_provider="google", model=self.model_name)
        return exc

    def completion(self, messages: list[dict[str, Any]], **kwargs) -> LLMResponse:
        from backend.llm.mappers.gemini import (
            extract_tool_calls,
            extract_text,
            ensure_non_empty_content,
            gemini_usage,
        )

        model_name, gen_cfg, system_instruction, history, prompt, tools, cache_name = (
            self._build_gemini_chat(messages, kwargs)
        )

        config: Any = {
            **gen_cfg,
            "tools": tools,
        }
        if cache_name:
            config["cached_content"] = cache_name
        else:
            config["system_instruction"] = system_instruction

        logger.debug("Gemini config: %s", config)
        logger.info(
            "GeminiClient.completion: model=%s, history_len=%d, prompt_len=%d, "
            "tools=%s, remaining_kwargs=%s",
            model_name,
            len(history),
            len(prompt) if isinstance(prompt, str) else 0,
            len(tools) if tools else 0,
            sorted(kwargs.keys()),
        )
        logger.info("GeminiClient.completion: creating chat session...")
        chat = self.client.chats.create(
            model=model_name,
            config=config,
            history=cast(Any, history),
        )
        logger.info("GeminiClient.completion: chat created, calling send_message...")
        try:
            response = chat.send_message(prompt, **kwargs)
        except Exception as e:
            logger.error("GeminiClient.completion: send_message raised %s: %s", type(e).__name__, e)
            raise self._map_gemini_error(e) from e
        logger.info("GeminiClient.completion: send_message returned successfully")
        tool_calls = extract_tool_calls(response)
        content = extract_text(response)
        content = ensure_non_empty_content(response, content, tool_calls)
        return LLMResponse(
            content=content,
            model=model_name,
            usage=gemini_usage(response),
            id="",
            finish_reason="stop",
            tool_calls=tool_calls,
        )

    async def acompletion(
        self, messages: list[dict[str, Any]], **kwargs
    ) -> LLMResponse:
        """Asynchronous completion."""
        from backend.llm.mappers.gemini import (
            extract_tool_calls,
            extract_text,
            ensure_non_empty_content,
            gemini_usage,
        )

        model_name, gen_cfg, system_instruction, history, prompt, tools, cache_name = (
            self._build_gemini_chat(messages, kwargs)
        )

        config: Any = {
            **gen_cfg,
            "tools": tools,
        }
        if cache_name:
            config["cached_content"] = cache_name
        else:
            config["system_instruction"] = system_instruction

        logger.debug("Gemini config: %s", config)

        chat = self.client.aio.chats.create(
            model=model_name,
            config=config,
            history=cast(Any, history),
        )

        try:
            response = await chat.send_message(prompt, **kwargs)
        except Exception as e:
            raise self._map_gemini_error(e) from e
        tool_calls = extract_tool_calls(response)
        content = extract_text(response)
        content = ensure_non_empty_content(response, content, tool_calls)
        return LLMResponse(
            content=content,
            model=model_name,
            usage=gemini_usage(response),
            id="",
            finish_reason="stop",
            tool_calls=tool_calls,
        )

    async def astream(
        self, messages: list[dict[str, Any]], **kwargs
    ) -> AsyncIterator[dict[str, Any]]:
        """Asynchronous streaming completion."""
        model_name, gen_cfg, system_instruction, history, prompt, tools, cache_name = (
            self._build_gemini_chat(messages, kwargs)
        )

        config: Any = {
            **gen_cfg,
            "tools": tools,
        }
        if cache_name:
            config["cached_content"] = cache_name
        else:
            config["system_instruction"] = system_instruction

        logger.debug("Gemini config: %s", config)

        chat = self.client.aio.chats.create(
            model=model_name,
            config=config,
            history=cast(Any, history),
        )

        try:
            stream = await chat.send_message_stream(prompt, **kwargs)
            async for chunk in stream:
                fcs = getattr(chunk, "function_calls", None)
                if fcs:
                    for idx, fc in enumerate(fcs):
                        import json
                        try:
                            _args = getattr(fc, "args", {})
                            if hasattr(type(fc), "to_dict") and _args:
                                _to_dict = getattr(type(fc), "to_dict")
                                if callable(_to_dict):
                                    args_dict = _to_dict(_args)
                                else:
                                    args_dict = _args
                            elif hasattr(_args, "items"):
                                args_dict = dict(_args.items())  # type: ignore[union-attr]
                            elif hasattr(_args, "__dict__"):
                                args_dict = _args.__dict__
                            else:
                                args_dict = _args

                            if hasattr(args_dict, "pb") and hasattr(args_dict, "items"):
                                args_dict = {k: v for k, v in args_dict.items()}  # type: ignore[union-attr]

                            if isinstance(args_dict, dict):
                                args_str = json.dumps(args_dict)
                            else:
                                args_str = json.dumps(getattr(fc, "args", {}))
                        except Exception:
                            args_str = "{}"
                        yield {
                            "choices": [{
                                "delta": {
                                    "tool_calls": [{
                                        "index": idx,
                                        "id": f"call_{fc.name}_{idx}",
                                        "type": "function",
                                        "function": {"name": fc.name, "arguments": args_str}
                                    }]
                                },
                                "finish_reason": None
                            }]
                        }
                text = chunk.text or ""
                if text:
                    yield {"choices": [{"delta": {"content": text}, "finish_reason": None}]}
        except Exception as e:
            raise self._map_gemini_error(e) from e
        yield {"choices": [{"delta": {}, "finish_reason": "stop"}]}


def get_direct_client(
    model: str, api_key: str, base_url: str | None = None
) -> DirectLLMClient:
    """Factory function to get the correct direct client using catalog-driven routing.

    This function automatically resolves the provider and base URL based on:
    1. The model catalog (catalog.toml)
    2. Local endpoint discovery (Ollama, LM Studio, vLLM)
    3. Provider heuristics for unknown models

    Args:
        model: Model name (e.g., "gpt-4o", "claude-opus-4", "ollama/llama3")
        api_key: API key for the provider
        base_url: Optional explicit base URL (overrides auto-resolution)

    Returns:
        Appropriate DirectLLMClient instance
    """
    from backend.llm.provider_resolver import get_resolver

    resolver = get_resolver()

    # Strip provider prefix if present (e.g., "ollama/llama3" → "llama3")
    stripped_model = resolver.strip_provider_prefix(model)

    # Resolve provider from catalog or heuristics
    provider = resolver.resolve_provider(model)

    # Resolve base URL (handles local discovery and environment variables)
    resolved_base_url = resolver.resolve_base_url(model, base_url)

    logger.debug(
        "Resolved model=%s → provider=%s, base_url=%s, stripped=%s",
        model,
        provider,
        resolved_base_url or "default",
        stripped_model,
    )

    # Route to appropriate client based on provider
    if provider == "anthropic":
        return AnthropicClient(model_name=stripped_model, api_key=api_key)

    if provider == "google":
        return GeminiClient(model_name=stripped_model, api_key=api_key)

    # All OpenAI-compatible providers use OpenAI client
    # (OpenAI, xAI, DeepSeek, Mistral, Ollama, LM Studio, vLLM, etc.)
    return OpenAIClient(
        model_name=stripped_model, api_key=api_key, base_url=resolved_base_url
    )
