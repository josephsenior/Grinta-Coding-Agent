"""Direct LLM clients for OpenAI, Anthropic, Google Gemini, and xAI Grok.

This module provides direct SDK integrations with major LLM providers,
offering a lightweight and stable alternative to multi-provider abstraction libraries.
"""

from __future__ import annotations

import json
import threading
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

import google.generativeai as genai
import httpx
from anthropic import Anthropic, AsyncAnthropic
from openai import AsyncOpenAI, OpenAI

from backend.core.logger import FORGE_logger as logger

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
        id: str = "",
        finish_reason: str = "stop",
        tool_calls: list[dict[str, Any]] | None = None,
        **kwargs,
    ):
        self.content = content
        self.model = model
        self.usage = usage
        self.id = kwargs.get("response_id", id)
        self.finish_reason = finish_reason
        self.tool_calls = tool_calls

        # Build nested structure for attribute-style access
        class Message:
            def __init__(self, content, role, tool_calls=None):
                self.content = content
                self.role = role
                self.tool_calls = tool_calls

        class Choice:
            def __init__(self, content, role, finish_reason, tool_calls=None):
                self.message = Message(content, role, tool_calls)
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
    async def astream(
        self, messages: list[dict[str, Any]], **kwargs
    ) -> AsyncIterator[dict[str, Any]]:  # type: ignore[override,misc]
        """Stream responses asynchronously. Returns an async iterator."""

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
        """Extract tool_calls from an OpenAI ChatCompletionMessage."""
        raw = getattr(message, "tool_calls", None)
        if not raw:
            return None
        result: list[dict[str, Any]] = []
        for tc in raw:
            entry: dict[str, Any] = {
                "id": tc.id,
                "type": tc.type,
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            result.append(entry)
        return result or None

    def completion(self, messages: list[dict[str, Any]], **kwargs) -> LLMResponse:
        if "model" not in kwargs:
            kwargs["model"] = self.model_name
        response = self.client.chat.completions.create(
            messages=messages,  # type: ignore[arg-type]
            **kwargs,
        )
        msg = response.choices[0].message
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
            finish_reason=response.choices[0].finish_reason,
            tool_calls=tool_calls,
        )

    async def acompletion(
        self, messages: list[dict[str, Any]], **kwargs
    ) -> LLMResponse:
        model = kwargs.pop("model", self.model_name)
        response = await self.async_client.chat.completions.create(
            model=model,
            messages=messages,  # type: ignore[arg-type]
            **kwargs,
        )
        msg = response.choices[0].message
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
            finish_reason=response.choices[0].finish_reason,
            tool_calls=tool_calls,
        )

    async def astream(
        self, messages: list[dict[str, Any]], **kwargs
    ) -> AsyncIterator[dict[str, Any]]:  # type: ignore[override,misc]
        kwargs["stream"] = True
        model = kwargs.pop("model", self.model_name)
        stream = await self.async_client.chat.completions.create(
            model=model,
            messages=messages,  # type: ignore[arg-type]
            **kwargs,
        )
        async for chunk in stream:  # type: ignore[attr-defined]
            yield chunk.model_dump()


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
        """Extract text and tool_use blocks from Anthropic response content.

        Returns:
            (text_content, tool_calls_or_None)
        """
        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        for block in content_blocks:
            block_type = getattr(block, "type", None)
            if block_type == "text":
                text_parts.append(block.text)
            elif block_type == "tool_use":
                tool_calls.append(
                    {
                        "id": block.id,
                        "type": "function",
                        "function": {
                            "name": block.name,
                            "arguments": json.dumps(block.input)
                            if isinstance(block.input, dict)
                            else str(block.input),
                        },
                    }
                )
        return "\n".join(text_parts), tool_calls or None

    def _prepare_anthropic_kwargs(
        self, messages: list[dict[str, Any]], kwargs: dict[str, Any]
    ) -> tuple[list, dict[str, Any]]:
        """Extract system message and set model for Anthropic calls."""
        system_msg = next(
            (m["content"] for m in messages if m["role"] == "system"), None
        )
        filtered = [m for m in messages if m["role"] != "system"]
        if "model" not in kwargs:
            kwargs["model"] = self.model_name
        if system_msg is not None:
            kwargs["system"] = system_msg
        return filtered, kwargs

    def completion(self, messages: list[dict[str, Any]], **kwargs) -> LLMResponse:
        filtered, kwargs = self._prepare_anthropic_kwargs(messages, kwargs)
        model = kwargs.pop("model", self.model_name)
        response = self.client.messages.create(
            model=model,
            messages=filtered,  # type: ignore[arg-type]
            **kwargs,
        )
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
        response = await self.async_client.messages.create(
            model=model,
            messages=filtered,  # type: ignore[arg-type]
            **kwargs,
        )
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
    ) -> AsyncIterator[dict[str, Any]]:  # type: ignore[override,misc]
        system_msg = next(
            (m["content"] for m in messages if m["role"] == "system"), None
        )
        filtered_messages = [m for m in messages if m["role"] != "system"]

        if "model" not in kwargs:
            kwargs["model"] = self.model_name

        async with self.async_client.messages.stream(
            messages=filtered_messages,  # type: ignore[arg-type]
            system=system_msg,  # type: ignore[arg-type]
            **kwargs,
        ) as stream:
            async for event in stream:
                # Convert Anthropic events to OpenAI-like chunks for compatibility
                if event.type == "content_block_delta":
                    yield {
                        "choices": [
                            {
                                "delta": {"content": event.delta.text},  # type: ignore[union-attr]
                                "finish_reason": None,
                            }
                        ]
                    }
                elif event.type == "message_stop":
                    yield {"choices": [{"delta": {}, "finish_reason": "stop"}]}


class GeminiClient(DirectLLMClient):
    """Client for Google Gemini."""

    def __init__(self, model_name: str, api_key: str):
        self._model_name = model_name
        genai.configure(api_key=api_key)
        self.api_key = api_key

    def _convert_messages(
        self, messages: list[dict[str, Any]]
    ) -> tuple[str | None, list[dict[str, Any]], bool]:
        """Convert messages to Gemini format, extracting system instruction.

        Returns:
            (system_instruction_or_None, gemini_history_messages, caching_requested)
        """
        system_instruction: str | None = None
        gemini_messages: list[dict[str, Any]] = []
        caching_requested = False

        for m in messages:
            content = m.get("content", "")
            
            # Handle list-style content (from Forge's message serialization)
            text_parts = []
            if isinstance(content, list):
                for item in content:
                    if item.get("type") == "text":
                        text_parts.append(item.get("text", ""))
                        if item.get("cache_prompt"):
                            caching_requested = True
                    # Image support for Gemini could be added here
                content = "\n".join(text_parts)
            
            if m["role"] == "system":
                system_instruction = content
                continue
            
            role = "user" if m["role"] == "user" else "model"
            gemini_messages.append({"role": role, "parts": [content]})
        
        return system_instruction, gemini_messages, caching_requested

    @staticmethod
    def _extract_gemini_generation_config(
        kwargs: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        """Pop generation-config keys from *kwargs* and return (model_name, gen_config)."""
        model_name = kwargs.pop("model", "")
        if "/" in model_name:
            model_name = model_name.split("/")[-1]
        gen_cfg: dict[str, Any] = {}
        for src, dst in [
            ("temperature", "temperature"),
            ("top_p", "top_p"),
            ("top_k", "top_k"),
            ("max_tokens", "max_output_tokens"),
            ("stop", "stop_sequences"),
        ]:
            if src in kwargs:
                gen_cfg[dst] = kwargs.pop(src)
        return model_name, gen_cfg

    @staticmethod
    def _extract_gemini_tool_calls(response: Any) -> list[dict[str, Any]] | None:
        """Extract function call parts from a Gemini response."""
        tool_calls: list[dict[str, Any]] = []
        for candidate in getattr(response, "candidates", []):
            for part in getattr(candidate, "content", {}).get("parts", []):
                fc = getattr(part, "function_call", None)
                if fc is None:
                    continue
                tool_calls.append(
                    {
                        "id": f"gemini-{len(tool_calls)}",
                        "type": "function",
                        "function": {
                            "name": fc.name,
                            "arguments": json.dumps(dict(fc.args)) if fc.args else "{}",
                        },
                    }
                )
        return tool_calls or None

    @staticmethod
    def _gemini_usage(response: Any) -> dict[str, int]:
        """Extract token usage from a Gemini response."""
        meta = getattr(response, "usage_metadata", None)
        return {
            "prompt_tokens": getattr(meta, "prompt_token_count", 0) if meta else 0,
            "completion_tokens": getattr(meta, "candidates_token_count", 0)
            if meta
            else 0,
            "total_tokens": getattr(meta, "total_token_count", 0) if meta else 0,
            "cache_read_tokens": getattr(meta, "cached_content_token_count", 0)
            if meta
            else 0,
        }

    def _build_gemini_chat(
        self, messages: list[dict[str, Any]], kwargs: dict[str, Any]
    ):
        """Shared setup for Gemini completion / acompletion / astream."""
        model_name, gen_cfg = self._extract_gemini_generation_config(kwargs)
        model_name = model_name or self.model_name
        if "/" in model_name:
            model_name = model_name.split("/")[-1]
        
        system_instruction, gemini_messages, caching_requested = self._convert_messages(messages)
        
        # Handle Context Caching if supported and requested
        from backend.llm.gemini_cache import gemini_cache_manager
        
        cache_name = None
        if caching_requested:
            # We cache everything up to the penultimate message (the history)
            # if history is substantial. For now, let's cache the whole history.
            history_to_cache = gemini_messages[:-1] if len(gemini_messages) > 1 else []
            if history_to_cache or system_instruction:
                cache_name = gemini_cache_manager.get_or_create_cache(
                    model=model_name,
                    system_instruction=system_instruction,
                    messages=history_to_cache
                )

        model_kwargs: dict[str, Any] = {"generation_config": gen_cfg} if gen_cfg else {}
        
        if cache_name:
            # When using a cache, the model is initialized with the cache name
            # and we ONLY send the remaining messages.
            model = genai.GenerativeModel(model_name, **model_kwargs)
            # Note: The SDK's start_chat doesn't directly take cache_name yet in all versions
            # so we use history for the non-cached part.
            prompt = gemini_messages[-1]["parts"][0] if gemini_messages else ""
            # If we cached the history, the history for start_chat is empty.
            chat = model.start_chat(history=[])
            # Inject cached_content into kwargs for the final send_message call
            kwargs["cached_content"] = cache_name
        else:
            if system_instruction:
                model_kwargs["system_instruction"] = system_instruction
            model = genai.GenerativeModel(model_name, **model_kwargs)
            prompt = gemini_messages[-1]["parts"][0] if gemini_messages else ""
            history = gemini_messages[:-1] if gemini_messages else []
            chat = model.start_chat(history=history)
            
        return model_name, chat, prompt

    def completion(self, messages: list[dict[str, Any]], **kwargs) -> LLMResponse:
        model_name, chat, prompt = self._build_gemini_chat(messages, kwargs)
        response = chat.send_message(prompt, **kwargs)
        return LLMResponse(
            content=response.text,
            model=model_name,
            usage=self._gemini_usage(response),
            id="",
            finish_reason="stop",
            tool_calls=self._extract_gemini_tool_calls(response),
        )

    async def acompletion(
        self, messages: list[dict[str, Any]], **kwargs
    ) -> LLMResponse:
        model_name, chat, prompt = self._build_gemini_chat(messages, kwargs)
        response = await chat.send_message_async(prompt, **kwargs)
        return LLMResponse(
            content=response.text,
            model=model_name,
            usage=self._gemini_usage(response),
            id="",
            finish_reason="stop",
            tool_calls=self._extract_gemini_tool_calls(response),
        )

    async def astream(
        self, messages: list[dict[str, Any]], **kwargs
    ) -> AsyncIterator[dict[str, Any]]:  # type: ignore[override,misc]
        model_name, chat, prompt = self._build_gemini_chat(messages, kwargs)
        response = await chat.send_message_async(prompt, stream=True, **kwargs)

        async for chunk in response:
            yield {
                "choices": [{"delta": {"content": chunk.text}, "finish_reason": None}]
            }
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
