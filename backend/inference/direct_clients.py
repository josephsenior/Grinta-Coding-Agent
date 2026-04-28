"""Direct LLM clients for OpenAI, Anthropic, Google Gemini, and xAI Grok.

This module provides direct SDK integrations with major LLM providers,
offering a lightweight and stable alternative to multi-provider abstraction libraries.
"""

from __future__ import annotations

import threading
import warnings
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, cast

import httpx
from anthropic import Anthropic, AsyncAnthropic

# google-genai subclasses aiohttp.ClientSession; aiohttp emits DeprecationWarning
# while ``_api_client`` is loading. A local catch is reliable regardless of
# PYTHONWARNINGS / filter registration order.
with warnings.catch_warnings():
    warnings.simplefilter('ignore', DeprecationWarning)
    from google import genai
from openai import AsyncOpenAI, OpenAI

from backend.cli.tool_call_display import flatten_tool_call_for_history
from backend.core import json_compat as json
from backend.core.logger import app_logger as logger
from backend.inference.direct_clients_anthropic_ops import (
    acompletion as _anthropic_acompletion,
    astream as _anthropic_astream,
    completion as _anthropic_completion,
    extract_anthropic_tool_calls as _extract_anthropic_tool_calls_impl,
    map_anthropic_error as _map_anthropic_error_impl,
    prepare_anthropic_kwargs as _prepare_anthropic_kwargs_impl,
)
from backend.inference.direct_clients_openai_ops import (
    acompletion as _openai_acompletion,
    astream as _openai_astream,
    clean_messages as _clean_messages_impl,
    completion as _openai_completion,
    extract_openai_tool_calls as _extract_openai_tool_calls_impl,
    map_openai_error as _map_openai_error_impl,
    strip_unsupported_params as _strip_unsupported_params_impl,
)

# Shared httpx pool: reuse provider/base_url transports across sessions so the
# direct SDK clients do not waste TCP connections on duplicate httpx clients.

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
    return f'{provider}::{base_url or "default"}'


def get_shared_http_client(provider: str, base_url: str | None = None) -> httpx.Client:
    """Return a shared *sync* httpx.Client for the given provider."""
    key = _pool_key(provider, base_url)
    if key not in _shared_sync_clients:
        with _pool_lock:
            if key not in _shared_sync_clients:
                _shared_sync_clients[key] = httpx.Client(
                    limits=_POOL_LIMITS,
                    timeout=httpx.Timeout(timeout=60.0, connect=10.0),
                    follow_redirects=True,
                )
                logger.debug('Created shared sync httpx pool for %s', key)
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
                    timeout=httpx.Timeout(timeout=60.0, connect=10.0),
                    follow_redirects=True,
                )
                logger.debug('Created shared async httpx pool for %s', key)
    return _shared_async_clients[key]


class LLMResponse:
    """Standardized response object for LLM calls with attribute and dict access."""

    def __init__(
        self,
        content: str,
        model: str,
        usage: dict[str, int],
        response_id: str = '',
        finish_reason: str = 'stop',
        tool_calls: list[dict[str, Any]] | None = None,
        reasoning_content: str = '',
        **kwargs,
    ):
        self.content = content
        self.model = model
        self.usage = usage
        self.id = kwargs.get('response_id', kwargs.get('id', response_id))
        self.finish_reason = self._normalize_finish_reason(finish_reason)
        self.tool_calls = self._normalize_tool_calls(tool_calls)
        # Reasoning/thinking text from models that surface it separately
        # (Gemini 2.5 thinking models, Claude extended thinking, o-series).
        # Empty string when the model does not produce thinking content.
        self.reasoning_content = reasoning_content

        # Build nested structure for attribute-style access
        class ToolCallFunction:
            def __init__(self, name: str, arguments: str):
                self.name = name
                self.arguments = arguments

            def model_dump(self):
                return {'name': self.name, 'arguments': self.arguments}

        class ToolCall:
            def __init__(self, tc_dict: dict[str, Any]):
                self.id = tc_dict.get('id')
                self.type = tc_dict.get('type', 'function')
                func_dict = tc_dict.get('function', {})
                self.function = ToolCallFunction(
                    name=func_dict.get('name', ''),
                    arguments=func_dict.get('arguments', '{}'),
                )
                # Support any other fields via setattr to be safe
                for k, v in tc_dict.items():
                    if k not in ['id', 'type', 'function']:
                        setattr(self, k, v)

            def model_dump(self):
                return {
                    'id': self.id,
                    'type': self.type,
                    'function': self.function.model_dump(),
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

        self.choices = [
            Choice(self.content, 'assistant', self.finish_reason, self.tool_calls)
        ]

    @staticmethod
    def _normalize_finish_reason(reason: str | None) -> str:
        if not reason:
            return 'stop'
        reason = str(reason).strip().lower()
        mapping = {
            'end_turn': 'stop',
            'max_tokens': 'length',
            'tool_use': 'tool_calls',
        }
        return mapping.get(reason, reason)

    @staticmethod
    def _normalize_tool_calls(
        tool_calls: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]] | None:
        if not tool_calls:
            return None
        normalized = []
        for i, tc in enumerate(tool_calls):
            # Ensure function arguments are JSON strings
            func = tc.get('function', {})
            args = func.get('arguments', '{}')
            if isinstance(args, dict):
                args_str = json.dumps(args, ensure_ascii=False, separators=(',', ':'))
            elif isinstance(args, str):
                args_str = args
            else:
                args_str = str(args)

            normalized.append(
                {
                    'id': tc.get('id', f'call_{i + 1}'),
                    'type': tc.get('type', 'function'),
                    'function': {
                        'name': func.get('name', ''),
                        'arguments': args_str,
                    },
                }
            )
        return normalized

    def to_dict(self) -> dict[str, Any]:
        return {
            'id': self.id,
            'model': self.model,
            'choices': [
                {
                    'message': {
                        'content': self.content,
                        'role': 'assistant',
                        'tool_calls': self.tool_calls,
                    },
                    'finish_reason': self.finish_reason,
                }
            ],
            'usage': self.usage,
        }

    def __getitem__(self, key: str):
        return self.to_dict()[key]


def _stringify_openai_metadata_value(value: Any) -> str:
    """Normalize metadata values for OpenAI-compatible APIs.

    Several compatible providers reject metadata unless all values are strings.
    """
    if value is None:
        return ''
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple, set)):
        return ','.join(
            item
            for item in (_stringify_openai_metadata_value(part) for part in value)
            if item
        )
    if isinstance(value, dict):
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(',', ':'),
            default=str,
        )
    return str(value)


def _sanitize_openai_compatible_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Normalize request kwargs for OpenAI-compatible APIs."""
    sanitized = dict(kwargs)
    extra_body = sanitized.get('extra_body')
    if not isinstance(extra_body, dict):
        return sanitized
    metadata = extra_body.get('metadata')
    if not isinstance(metadata, dict):
        return sanitized

    sanitized_extra_body = dict(extra_body)
    sanitized_extra_body['metadata'] = {
        str(key): _stringify_openai_metadata_value(value)
        for key, value in metadata.items()
    }
    sanitized['extra_body'] = sanitized_extra_body
    return sanitized


def _extract_openai_message_text(content: Any) -> str:
    """Extract plain text from OpenAI-style message content."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get('type') == 'text':
                text = item.get('text')
                if text:
                    parts.append(str(text))
        return '\n'.join(parts)
    if content is None:
        return ''
    return str(content)


@dataclass(frozen=True)
class TransportProfile:
    """Capabilities of the transport layer between client and LLM backend.

    Resolved once at client creation based on model family vs transport
    protocol. Replaces ad-hoc model-name pattern matching with deterministic
    cross-family detection.
    """

    supports_request_metadata: bool = True
    """True only for the real OpenAI API (api.openai.com)."""

    supports_tool_replay: bool = True
    """True when prior tool-call messages can be replayed verbatim.

    False for Google-family models on OpenAI-compatible proxies — Google
    backends expect proprietary ``thought_signature`` data that gets lost
    in the OpenAI translation.
    """

    flatten_tool_history: bool = False
    """True when tool-call history must be flattened to plain text.

    Distinct from ``supports_tool_replay``: a provider may accept tool
    messages in the wire format but still need history flattened for
    correctness on a foreign-protocol proxy.
    """

    requires_thought_signature: bool = False
    """True when the backend requires a ``thought_signature`` field.

    Currently Google-native only.  When this profile is used via an
    OpenAI-compatible proxy the signature is lost and responses will
    degrade silently — callers should warn.
    """


def _resolve_transport_profile(
    model_family: str | None,
    base_url: str | None,
) -> TransportProfile:
    """Resolve transport capabilities for an OpenAI-compatible client.

    The decision combines the **model family** (queried via
    :func:`backend.inference.provider_capabilities.get_provider_capabilities`
    so adding a new provider quirk only touches the registry) with the
    transport URL. Native SDK clients (``AnthropicClient``, ``GeminiClient``)
    don't need this — they speak their own protocol natively.

    Args:
        model_family: Provider that owns the model (e.g. ``"openai"``,
            ``"google"``, ``"anthropic"``, ``"deepseek"``). Comes from
            ``resolve_provider()``.
        base_url: The endpoint URL being used. ``None`` means the SDK
            default.
    """
    from backend.inference.provider_capabilities import get_provider_capabilities

    # Metadata: only the real OpenAI API accepts the `metadata` request field.
    is_native_openai = model_family == 'openai' and (
        not base_url
        or str(base_url)
        .strip()
        .rstrip('/')
        .lower()
        .startswith('https://api.openai.com')
    )

    # Tool replay correctness comes from the provider capability registry:
    # providers like Google require proprietary fields (e.g. thought_signature)
    # that get lost when routed through OpenAI-compatible proxies, causing
    # INVALID_ARGUMENT errors on later turns.
    caps = get_provider_capabilities(model_family)

    return TransportProfile(
        supports_request_metadata=is_native_openai,
        supports_tool_replay=caps.supports_tool_replay,
        flatten_tool_history=caps.flatten_tool_history,
        requires_thought_signature=caps.requires_thought_signature,
    )


def _normalize_cross_family_tool_messages(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Flatten tool-call history into plain text for cross-family proxy routes.

    When a model family (e.g. Google) is routed through a different transport
    protocol (e.g. OpenAI-compatible), prior tool-call content blocks may lack
    proprietary fields the backend expects. Flattening them into readable text
    preserves the information without triggering protocol-level errors.
    """
    cleaned: list[dict[str, Any]] = []
    for raw_msg in messages:
        msg = dict(raw_msg)
        msg.pop('tool_ok', None)

        role = msg.get('role')
        if role == 'assistant' and isinstance(msg.get('tool_calls'), list):
            text = _extract_openai_message_text(msg.get('content'))
            tool_lines: list[str] = []
            for tc in msg.get('tool_calls', []) or []:
                if not isinstance(tc, dict):
                    continue
                fn = tc.get('function') or {}
                name = str(fn.get('name') or 'tool')
                arguments = str(fn.get('arguments') or '{}')
                tool_lines.append(flatten_tool_call_for_history(name, arguments))
            normalized = {k: v for k, v in msg.items() if k != 'tool_calls'}
            normalized['content'] = (
                '\n'.join(part for part in [text, *tool_lines] if part)
                or '[Assistant requested tool execution.]'
            )
            cleaned.append(normalized)
            continue

        if role == 'tool':
            tool_name = str(msg.get('name') or 'tool')
            tool_output = _extract_openai_message_text(msg.get('content'))
            cleaned.append(
                {
                    'role': 'user',
                    'content': (
                        f'[Tool result from {tool_name}]\n{tool_output}'.strip()
                        or f'[Tool result from {tool_name}]'
                    ),
                }
            )
            continue

        cleaned.append(msg)
    return cleaned


class DirectLLMClient(ABC):
    """Abstract base class for direct LLM clients."""

    _model_name: str = ''

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
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream responses asynchronously. Returns an async iterator."""
        yield {}  # type: ignore

    def __init_subclass__(cls, **kwargs):
        """Ensure subclasses define model_name attribute."""
        super().__init_subclass__(**kwargs)

    @property
    def model_name(self) -> str:
        """Get the model name. Must be implemented by subclasses."""
        if not self._model_name:
            raise NotImplementedError('Subclasses must set _model_name attribute')
        return self._model_name

    def get_completion_cost(
        self, prompt_tokens: int, completion_tokens: int, config: Any | None = None
    ) -> float:
        """Calculate completion cost for this client's model."""
        from backend.inference.cost_tracker import get_completion_cost

        return get_completion_cost(
            self.model_name, prompt_tokens, completion_tokens, config
        )


class OpenAIClient(DirectLLMClient):
    """Client for OpenAI and OpenAI-compatible APIs (like xAI Grok)."""

    def __init__(
        self,
        model_name: str,
        api_key: str,
        base_url: str | None = None,
        profile: TransportProfile | None = None,
    ):
        self._model_name = model_name
        self._api_base_url = base_url
        self._profile = profile or TransportProfile()
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            http_client=get_shared_http_client('openai', base_url),
        )
        self.async_client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            http_client=get_shared_async_http_client('openai', base_url),
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
        return _openai_completion(self, messages, **kwargs)

    async def acompletion(
        self, messages: list[dict[str, Any]], **kwargs
    ) -> LLMResponse:
        return await _openai_acompletion(self, messages, **kwargs)

    async def astream(
        self, messages: list[dict[str, Any]], **kwargs
    ) -> AsyncIterator[dict[str, Any]]:
        async for chunk in _openai_astream(self, messages, **kwargs):
            yield chunk


class AnthropicClient(DirectLLMClient):
    """Client for Anthropic Claude."""

    def __init__(self, model_name: str, api_key: str):
        self._model_name = model_name
        self.client = Anthropic(
            api_key=api_key,
            http_client=get_shared_http_client('anthropic'),
        )
        self.async_client = AsyncAnthropic(
            api_key=api_key,
            http_client=get_shared_async_http_client('anthropic'),
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
        return _anthropic_completion(self, messages, **kwargs)

    async def acompletion(
        self, messages: list[dict[str, Any]], **kwargs
    ) -> LLMResponse:
        return await _anthropic_acompletion(self, messages, **kwargs)

    async def astream(
        self, messages: list[dict[str, Any]], **kwargs
    ) -> AsyncIterator[dict[str, Any]]:
        async for chunk in _anthropic_astream(self, messages, **kwargs):
            yield chunk


class GeminiClient(DirectLLMClient):
    """Client for Google Gemini."""

    def __init__(self, model_name: str, api_key: str):
        # Never log secrets (even partial key prefixes/suffixes).
        logger.debug(
            'Initializing Gemini client (api_key_set=%s, api_key_len=%s)',
            bool(api_key),
            len(api_key) if api_key else 0,
        )
        self._model_name = model_name
        self.api_key = api_key

        # Add timeout to prevent infinite hanging when the API is overloaded
        from google.genai.types import HttpOptions

        http_options = HttpOptions(timeout=45000)  # 45 seconds
        self.client = genai.Client(api_key=api_key, http_options=http_options)

    def _resolve_gemini_model_name(self, model_name: str | None) -> str:
        """Normalize model name for Gemini API."""
        name = model_name or self.model_name
        return name.split('/')[-1] if '/' in name else name

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
        from backend.inference.prompt_cache import get_prompt_cache

        history_to_cache = history_messages if history_messages else []
        if not history_to_cache and not system_instruction:
            return None
        backend = get_prompt_cache('google')
        return backend.get_or_create_cache_handle(
            client=self.client,
            model=model_name,
            system_instruction=system_instruction,
            messages=history_to_cache,
        )

    def _extract_gemini_text(self, message: dict[str, Any]) -> str:
        parts = message.get('parts') or []
        text_parts: list[str] = []
        for part in parts:
            if isinstance(part, dict):
                text = part.get('text')
                if isinstance(text, str) and text:
                    text_parts.append(text)
        return '\n'.join(text_parts)

    def _split_gemini_history_and_prompt(
        self, gemini_messages: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], str]:
        if not gemini_messages:
            return [], ''

        active_messages = list(gemini_messages)
        while active_messages and active_messages[-1].get('role') != 'user':
            active_messages.pop()

        if not active_messages:
            logger.warning(
                'GeminiClient: no trailing user message found; falling back to last message text'
            )
            fallback_prompt = self._extract_gemini_text(gemini_messages[-1])
            fallback_history = gemini_messages[:-1] if len(gemini_messages) > 1 else []
            return fallback_history, fallback_prompt

        prompt_start = len(active_messages) - 1
        while (
            prompt_start > 0 and active_messages[prompt_start - 1].get('role') == 'user'
        ):
            prompt_start -= 1

        history = active_messages[:prompt_start]
        prompt = '\n'.join(
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
        from backend.inference.mappers.gemini import (
            convert_messages,
            extract_generation_config,
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

    @staticmethod
    def _build_gemini_request_config(
        gen_cfg: dict[str, Any],
        tools: list | None,
        system_instruction: str | None,
        cache_name: str | None,
    ) -> dict[str, Any]:
        config: dict[str, Any] = {
            **gen_cfg,
            'tools': tools,
        }
        if cache_name:
            config['cached_content'] = cache_name
        else:
            config['system_instruction'] = system_instruction
        return config

    @staticmethod
    def _log_gemini_exception(exc: Exception) -> None:
        logger.error('=' * 80)
        logger.error('GOOGLE GENAI EXCEPTION: %s %s', type(exc), exc)
        if hasattr(exc, 'code'):
            logger.error('CODE: %s', exc.code)
        if hasattr(exc, 'message'):
            logger.error('MESSAGE: %s', exc.message)
        if hasattr(exc, 'details'):
            logger.error('DETAILS: %s', exc.details)
        logger.error('=' * 80)

    @staticmethod
    def _is_gemini_api_key_error(error_str: str) -> bool:
        return 'api key' in error_str and (
            'not found' in error_str
            or 'invalid api key' in error_str
            or 'api_key_invalid' in error_str
        )

    def _map_gemini_api_error(self, exc: Any, error_str: str) -> Exception:
        from backend.inference.exceptions import (
            BadRequestError,
            ContextWindowExceededError,
            InternalServerError,
            NotFoundError,
            RateLimitError,
            ServiceUnavailableError,
            is_context_window_error,
        )
        from backend.inference.exceptions import (
            APIError as ProviderAPIError,
        )

        if self._is_gemini_api_key_error(error_str):
            from backend.inference.exceptions import AuthenticationError

            return AuthenticationError(
                str(exc), llm_provider='google', model=self.model_name
            )
        if exc.code == 429 or 'quota' in error_str or 'rate limit' in error_str:
            return RateLimitError(
                str(exc), llm_provider='google', model=self.model_name
            )
        if (
            exc.code == 401
            or 'unauthorized' in error_str
            or 'invalid api key' in error_str
        ):
            from backend.inference.exceptions import AuthenticationError

            return AuthenticationError(
                str(exc), llm_provider='google', model=self.model_name
            )
        if exc.code == 404 or 'not found' in error_str:
            return NotFoundError(
                str(exc), llm_provider='google', model=self.model_name
            )
        if (
            exc.code in (500, 502, 503, 504)
            or 'unavailable' in error_str
            or 'overloaded' in error_str
        ):
            return ServiceUnavailableError(
                str(exc), llm_provider='google', model=self.model_name
            )
        if exc.code == 400:
            if is_context_window_error(error_str, exc):
                return ContextWindowExceededError(
                    str(exc), llm_provider='google', model=self.model_name
                )
            return BadRequestError(
                str(exc), llm_provider='google', model=self.model_name
            )
        if exc.code and exc.code >= 500:
            return InternalServerError(
                str(exc), llm_provider='google', model=self.model_name
            )
        return ProviderAPIError(
            str(exc), llm_provider='google', model=self.model_name
        )

    def _map_gemini_error(self, exc: Exception) -> Exception:
        """Map google.genai exceptions to App LLM exceptions."""
        import asyncio

        import aiohttp
        from google.genai.errors import APIError

        from backend.inference.exceptions import (
            APIConnectionError,
            AuthenticationError,
            BadRequestError,
            ContextWindowExceededError,
            InternalServerError,
            NotFoundError,
            RateLimitError,
            ServiceUnavailableError,
            Timeout,
            is_context_window_error,
        )
        from backend.inference.exceptions import (
            APIError as ProviderAPIError,
        )

        self._log_gemini_exception(exc)

        if isinstance(exc, (asyncio.TimeoutError, httpx.TimeoutException)):
            return Timeout(str(exc), llm_provider='google', model=self.model_name)
        if isinstance(exc, (aiohttp.ClientError, httpx.RequestError)):
            return APIConnectionError(
                str(exc), llm_provider='google', model=self.model_name
            )

        if isinstance(exc, APIError):
            return self._map_gemini_api_error(exc, str(exc).lower())
        return exc

    @staticmethod
    def _update_gemini_stream_usage(
        chunk: Any,
        *,
        input_tokens: int,
        output_tokens: int,
    ) -> tuple[int, int]:
        usage_metadata = getattr(chunk, 'usage_metadata', None)
        if usage_metadata is None:
            return input_tokens, output_tokens
        return (
            int(getattr(usage_metadata, 'prompt_token_count', 0) or 0),
            int(getattr(usage_metadata, 'candidates_token_count', 0) or 0),
        )

    @staticmethod
    def _serialize_gemini_function_args(function_call: Any) -> str:
        try:
            raw_args = getattr(function_call, 'args', {})
            if hasattr(type(function_call), 'to_dict') and raw_args:
                to_dict = getattr(type(function_call), 'to_dict')
                args_dict = to_dict(raw_args) if callable(to_dict) else raw_args
            elif hasattr(raw_args, 'items'):
                args_dict = dict(raw_args.items())  # type: ignore[union-attr]
            elif hasattr(raw_args, '__dict__'):
                args_dict = raw_args.__dict__
            else:
                args_dict = raw_args

            if hasattr(args_dict, 'pb') and hasattr(args_dict, 'items'):
                args_dict = dict(args_dict.items())  # type: ignore[union-attr]

            payload = args_dict if isinstance(args_dict, dict) else raw_args
            return json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
        except Exception:
            return '{}'

    def _gemini_tool_call_chunks(
        self, chunk: Any, start_index: int
    ) -> tuple[list[dict[str, Any]], int]:
        function_calls = getattr(chunk, 'function_calls', None) or []
        chunks: list[dict[str, Any]] = []
        next_index = start_index
        for function_call in function_calls:
            chunks.append(
                {
                    'choices': [
                        {
                            'delta': {
                                'tool_calls': [
                                    {
                                        'index': next_index,
                                        'id': f'call_{function_call.name}_{next_index}',
                                        'type': 'function',
                                        'function': {
                                            'name': function_call.name,
                                            'arguments': self._serialize_gemini_function_args(
                                                function_call
                                            ),
                                        },
                                    }
                                ]
                            },
                            'finish_reason': None,
                        }
                    ]
                }
            )
            next_index += 1
        return chunks, next_index

    @staticmethod
    def _gemini_text_chunk(text: str) -> dict[str, Any]:
        return {
            'choices': [{'delta': {'content': text}, 'finish_reason': None}]
        }

    @staticmethod
    def _gemini_reasoning_chunks(chunk: Any) -> list[dict[str, Any]]:
        candidates = getattr(chunk, 'candidates', None) or []
        chunks: list[dict[str, Any]] = []
        for candidate in candidates:
            candidate_content = getattr(candidate, 'content', None)
            if candidate_content is None:
                continue
            for part in getattr(candidate_content, 'parts', []):
                if not getattr(part, 'thought', False):
                    continue
                thought_text = getattr(part, 'text', '') or ''
                if thought_text:
                    chunks.append(
                        {
                            'choices': [
                                {
                                    'delta': {'reasoning_content': thought_text},
                                    'finish_reason': None,
                                }
                            ]
                        }
                    )
        return chunks

    @staticmethod
    def _gemini_finish_chunks(
        input_tokens: int, output_tokens: int
    ) -> list[dict[str, Any]]:
        chunks: list[dict[str, Any]] = []
        if input_tokens or output_tokens:
            chunks.append(
                {
                    'choices': [],
                    'usage': {
                        'prompt_tokens': input_tokens,
                        'completion_tokens': output_tokens,
                        'total_tokens': input_tokens + output_tokens,
                    },
                }
            )
        chunks.append({'choices': [{'delta': {}, 'finish_reason': 'stop'}]})
        return chunks

    def completion(self, messages: list[dict[str, Any]], **kwargs) -> LLMResponse:
        from backend.inference.mappers.gemini import (
            ensure_non_empty_content,
            extract_text,
            extract_thinking,
            extract_tool_calls,
            gemini_usage,
        )

        model_name, gen_cfg, system_instruction, history, prompt, tools, cache_name = (
            self._build_gemini_chat(messages, kwargs)
        )

        config: Any = self._build_gemini_request_config(
            gen_cfg,
            tools,
            system_instruction,
            cache_name,
        )

        logger.debug('Gemini config: %s', config)
        logger.info(
            'GeminiClient.completion: model=%s, history_len=%d, prompt_len=%d, '
            'tools=%s, remaining_kwargs=%s',
            model_name,
            len(history),
            len(prompt) if isinstance(prompt, str) else 0,
            len(tools) if tools else 0,
            sorted(kwargs.keys()),
        )
        logger.info('GeminiClient.completion: creating chat session...')
        chat = self.client.chats.create(
            model=model_name,
            config=config,
            history=cast(Any, history),
        )
        logger.info('GeminiClient.completion: chat created, calling send_message...')
        try:
            response = chat.send_message(prompt, **kwargs)
        except Exception as e:
            logger.error(
                'GeminiClient.completion: send_message raised %s: %s',
                type(e).__name__,
                e,
            )
            raise self._map_gemini_error(e) from e
        logger.info('GeminiClient.completion: send_message returned successfully')
        tool_calls = extract_tool_calls(response)
        content = extract_text(response)
        content = ensure_non_empty_content(response, content, tool_calls)
        return LLMResponse(
            content=content,
            model=model_name,
            usage=gemini_usage(response),
            id='',
            finish_reason='stop',
            tool_calls=tool_calls,
            reasoning_content=extract_thinking(response),
        )

    async def acompletion(
        self, messages: list[dict[str, Any]], **kwargs
    ) -> LLMResponse:
        """Asynchronous completion."""
        from backend.inference.mappers.gemini import (
            ensure_non_empty_content,
            extract_text,
            extract_thinking,
            extract_tool_calls,
            gemini_usage,
        )

        model_name, gen_cfg, system_instruction, history, prompt, tools, cache_name = (
            self._build_gemini_chat(messages, kwargs)
        )

        config: Any = self._build_gemini_request_config(
            gen_cfg,
            tools,
            system_instruction,
            cache_name,
        )

        logger.debug('Gemini config: %s', config)

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
            id='',
            finish_reason='stop',
            tool_calls=tool_calls,
            reasoning_content=extract_thinking(response),
        )

    async def astream(
        self, messages: list[dict[str, Any]], **kwargs
    ) -> AsyncIterator[dict[str, Any]]:
        """Asynchronous streaming completion."""
        model_name, gen_cfg, system_instruction, history, prompt, tools, cache_name = (
            self._build_gemini_chat(messages, kwargs)
        )

        config: Any = self._build_gemini_request_config(
            gen_cfg,
            tools,
            system_instruction,
            cache_name,
        )

        logger.debug('Gemini config: %s', config)

        chat = self.client.aio.chats.create(
            model=model_name,
            config=config,
            history=cast(Any, history),
        )

        try:
            stream = await chat.send_message_stream(prompt, **kwargs)
            fc_idx_counter = 0
            _gemini_input_tokens: int = 0
            _gemini_output_tokens: int = 0
            async for chunk in stream:
                _gemini_input_tokens, _gemini_output_tokens = (
                    self._update_gemini_stream_usage(
                        chunk,
                        input_tokens=_gemini_input_tokens,
                        output_tokens=_gemini_output_tokens,
                    )
                )
                tool_chunks, fc_idx_counter = self._gemini_tool_call_chunks(
                    chunk,
                    fc_idx_counter,
                )
                for tool_chunk in tool_chunks:
                    yield tool_chunk

                text = chunk.text or ''
                if text:
                    yield self._gemini_text_chunk(text)

                for reasoning_chunk in self._gemini_reasoning_chunks(chunk):
                    yield reasoning_chunk
        except Exception as e:
            raise self._map_gemini_error(e) from e
        for finish_chunk in self._gemini_finish_chunks(
            _gemini_input_tokens,
            _gemini_output_tokens,
        ):
            yield finish_chunk


def get_direct_client(
    model: str, api_key: str, base_url: str | None = None
) -> DirectLLMClient:
    """Factory function to get the correct direct client using explicit routing.

    This function automatically resolves the provider and base URL based on:
    1. Explicit provider prefix (``provider/model``)
    2. Exact model catalog entries (catalog.json)
    3. Local endpoint discovery (Ollama, LM Studio, vLLM)

    Args:
        model: Model name (e.g., "gpt-4o", "claude-opus-4", "ollama/llama3")
        api_key: API key for the provider
        base_url: Optional explicit base URL (overrides auto-resolution)

    Returns:
        Appropriate DirectLLMClient instance
    """
    from backend.inference.provider_resolver import get_resolver

    resolver = get_resolver()

    # Strip provider prefix if present (e.g., "ollama/llama3" → "llama3")
    stripped_model = resolver.strip_provider_prefix(model)

    # Resolve provider from explicit prefix or exact catalog entry
    provider = resolver.resolve_provider(model)

    # Resolve base URL (handles local discovery and environment variables)
    resolved_base_url = resolver.resolve_base_url(model, base_url)

    logger.debug(
        'Resolved model=%s → provider=%s, base_url=%s, stripped=%s',
        model,
        provider,
        resolved_base_url or 'default',
        stripped_model,
    )

    # When a custom base_url is provided that differs from the provider's own
    # native endpoint, the caller is routing the model through a third-party
    # proxy (e.g. Lightning AI, OpenRouter).  In that case we MUST use the
    # OpenAI-compatible client with the *original* model name so the proxy
    # receives the full identifier it expects (e.g.
    # "google/gemini-3-flash-preview" on Lightning AI).
    if resolved_base_url:
        # Collect known native endpoints for providers that have their own SDK
        # clients (i.e. Anthropic and Google).  All other providers already use
        # the OpenAI-compatible client so no special handling is needed.
        _NATIVE_ENDPOINTS: dict[str, str] = {
            'anthropic': 'https://api.anthropic.com',
            'google': 'https://generativelanguage.googleapis.com',
        }
        native = _NATIVE_ENDPOINTS.get(provider or '', '')
        is_native = native and resolved_base_url.rstrip('/').startswith(
            native.rstrip('/')
        )
        if not is_native and provider in ('anthropic', 'google'):
            # Proxy route: use OpenAI-compatible client with full model name
            profile = _resolve_transport_profile(provider, resolved_base_url)
            return OpenAIClient(
                model_name=model,
                api_key=api_key,
                base_url=resolved_base_url,
                profile=profile,
            )

    # Route to appropriate client based on provider
    if provider == 'anthropic':
        return AnthropicClient(model_name=stripped_model, api_key=api_key)

    if provider == 'google':
        return GeminiClient(model_name=stripped_model, api_key=api_key)

    # All OpenAI-compatible providers use OpenAI client
    # (OpenAI, xAI, DeepSeek, Mistral, Ollama, LM Studio, vLLM, Lightning, etc.)
    #
    # Detect true model family from stripped_model, not provider.
    # Example: model='openai/google/gemini-3-flash-preview' → provider='openai'
    # but stripped_model='google/gemini-3-flash-preview' → family='google'.
    # Lightning AI canonicalizes all models with an 'openai/' transport prefix,
    # which hides the actual model family from the outer provider field.
    model_family = provider
    if '/' in stripped_model:
        try:
            model_family = resolver.resolve_provider(stripped_model)
        except (ValueError, Exception):
            pass

    profile = _resolve_transport_profile(model_family, resolved_base_url)
    return OpenAIClient(
        model_name=stripped_model,
        api_key=api_key,
        base_url=resolved_base_url,
        profile=profile,
    )
