"""Base classes and shared utilities for direct LLM clients."""

from __future__ import annotations

import asyncio
import threading
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

import httpx

from backend.core import json_compat as json
from backend.core.logging.logger import app_logger as logger
from backend.inference.tool_support.tool_history import flatten_tool_call_for_history
from backend.inference.tool_support.tool_types import is_valid_tool_call_name

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


def _normalize_timeout_seconds(timeout: float | int | None) -> float | None:
    if timeout is None:
        return None
    try:
        value = float(timeout)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def bounded_llm_http_timeout(
    request_timeout: float | int | None = None,
    *,
    streaming: bool = False,
) -> httpx.Timeout:
    """Build ``httpx.Timeout`` with bounded socket-level connect/read ceilings.

    The overall *timeout* follows the logical request budget (model thinking
    time) but connect, read, write, and pool waits are capped so dead sockets
    and stalled streams fail within seconds and route to retry logic.

    Streaming calls use a higher per-read ceiling aligned with
    ``APP_LLM_STREAM_CHUNK_TIMEOUT_SECONDS`` so slow token delivery does not
    trip the non-streaming 30s read cap before the chunk watchdog fires.
    """
    from backend.core.constants import (
        LLM_HTTP_CONNECT_TIMEOUT_SECONDS,
        LLM_HTTP_POOL_TIMEOUT_SECONDS,
        LLM_HTTP_READ_TIMEOUT_SECONDS,
        LLM_HTTP_WRITE_TIMEOUT_SECONDS,
        LLM_STREAM_CHUNK_TIMEOUT_SECONDS,
    )

    total = _normalize_timeout_seconds(request_timeout) or 60.0
    if streaming:
        read_floor = max(
            LLM_HTTP_READ_TIMEOUT_SECONDS, LLM_STREAM_CHUNK_TIMEOUT_SECONDS
        )
        read_cap = min(read_floor, total)
    else:
        read_cap = min(LLM_HTTP_READ_TIMEOUT_SECONDS, total)
    return httpx.Timeout(
        timeout=total,
        connect=LLM_HTTP_CONNECT_TIMEOUT_SECONDS,
        read=read_cap,
        write=min(LLM_HTTP_WRITE_TIMEOUT_SECONDS, total),
        pool=LLM_HTTP_POOL_TIMEOUT_SECONDS,
    )


def _shared_llm_pool_timeout() -> httpx.Timeout:
    """Default socket timeouts for pooled LLM httpx clients.

    These transports serve streaming completions. When
    ``APP_LLM_STEP_TIMEOUT_SECONDS`` is unset (default), there is no outer
    wall-clock cap on the whole completion--only inter-chunk stalls are bounded
    via ``APP_LLM_STREAM_CHUNK_TIMEOUT_SECONDS`` at the socket read layer and
    the executor chunk watchdog. Set ``APP_LLM_STEP_TIMEOUT_SECONDS`` only when
    opting into a blunt whole-step cap.
    """
    from backend.core.constants import (
        LLM_HTTP_CONNECT_TIMEOUT_SECONDS,
        LLM_HTTP_POOL_TIMEOUT_SECONDS,
        LLM_HTTP_WRITE_TIMEOUT_SECONDS,
        LLM_STREAM_CHUNK_TIMEOUT_SECONDS,
    )
    from backend.core.timeouts.llm_step_timeout import llm_step_timeout_seconds_from_env

    step_timeout = llm_step_timeout_seconds_from_env()
    if step_timeout is not None:
        return bounded_llm_http_timeout(step_timeout, streaming=True)

    return httpx.Timeout(
        timeout=None,
        connect=LLM_HTTP_CONNECT_TIMEOUT_SECONDS,
        read=LLM_STREAM_CHUNK_TIMEOUT_SECONDS,
        write=LLM_HTTP_WRITE_TIMEOUT_SECONDS,
        pool=LLM_HTTP_POOL_TIMEOUT_SECONDS,
    )


def _coerce_bounded_request_timeout(
    value: Any,
    default_total: float | None,
    *,
    streaming: bool = False,
) -> httpx.Timeout:
    """Normalize SDK timeout kwargs to a bounded ``httpx.Timeout``."""
    if isinstance(value, httpx.Timeout):
        timeout_total = getattr(value, 'timeout', None) or getattr(value, 'read', None)
        return bounded_llm_http_timeout(
            timeout_total if timeout_total else default_total,
            streaming=streaming,
        )
    if isinstance(value, (int, float)):
        return bounded_llm_http_timeout(float(value), streaming=streaming)
    if default_total is not None:
        return bounded_llm_http_timeout(default_total, streaming=streaming)
    return bounded_llm_http_timeout(None, streaming=streaming)


def _with_default_timeout(
    kwargs: dict[str, Any],
    timeout: float | int | None,
    *,
    streaming: bool = False,
) -> dict[str, Any]:
    normalized = _normalize_timeout_seconds(timeout)
    if 'timeout' in kwargs:
        return {
            **kwargs,
            'timeout': _coerce_bounded_request_timeout(
                kwargs['timeout'], normalized, streaming=streaming
            ),
        }
    if normalized is None:
        return kwargs
    return {
        **kwargs,
        'timeout': bounded_llm_http_timeout(normalized, streaming=streaming),
    }


def _gemini_timeout_ms(timeout: float | int | None) -> int:
    normalized = _normalize_timeout_seconds(timeout)
    if normalized is None:
        return 45000
    return max(1, int(normalized * 1000))


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
                    timeout=_shared_llm_pool_timeout(),
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
                    timeout=_shared_llm_pool_timeout(),
                    follow_redirects=True,
                )
                logger.debug('Created shared async httpx pool for %s', key)
    return _shared_async_clients[key]


def _drain_shared_http_clients() -> tuple[list[httpx.Client], list[httpx.AsyncClient]]:
    with _pool_lock:
        sync_clients = list(_shared_sync_clients.values())
        async_clients = list(_shared_async_clients.values())
        _shared_sync_clients.clear()
        _shared_async_clients.clear()
    return sync_clients, async_clients


async def _aclose_async_clients(clients: list[httpx.AsyncClient]) -> None:
    for client in clients:
        with suppress(Exception):
            await client.aclose()


def close_shared_http_clients() -> None:
    """Close shared HTTP pools and clear the global pool cache.

    Prefer :func:`aclose_shared_http_clients` from async shutdown paths so async
    clients are awaited deterministically. This sync helper still closes async
    pools when no event loop is running, and schedules closure on the running
    loop otherwise.
    """
    sync_clients, async_clients = _drain_shared_http_clients()
    for client in sync_clients:
        with suppress(Exception):
            client.close()
    if not async_clients:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(_aclose_async_clients(async_clients))
        return
    for async_client in async_clients:
        loop.create_task(async_client.aclose())


async def aclose_shared_http_clients() -> None:
    """Async close shared sync/async HTTP pools and clear the pool cache."""
    sync_clients, async_clients = _drain_shared_http_clients()
    for client in sync_clients:
        with suppress(Exception):
            client.close()
    await _aclose_async_clients(async_clients)


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
            def __init__(
                self,
                content,
                role,
                tool_calls_dict=None,
                reasoning_content: str = '',
            ):
                self.content = content
                self.role = role
                self.reasoning_content = reasoning_content
                self.tool_calls = (
                    [ToolCall(tc) for tc in tool_calls_dict]
                    if tool_calls_dict
                    else None
                )

        class Choice:
            def __init__(
                self,
                content,
                role,
                finish_reason,
                tool_calls_dict=None,
                reasoning_content: str = '',
            ):
                self.message = Message(
                    content,
                    role,
                    tool_calls_dict,
                    reasoning_content=reasoning_content,
                )
                self.finish_reason = finish_reason

        self.choices = [
            Choice(
                self.content,
                'assistant',
                self.finish_reason,
                self.tool_calls,
                reasoning_content=self.reasoning_content,
            )
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
            name = func.get('name', '')
            if not is_valid_tool_call_name(name):
                logger.warning(
                    'Ignoring malformed provider tool call with invalid function name: %r',
                    name,
                )
                continue
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
                        'name': str(name).strip(),
                        'arguments': args_str,
                    },
                }
            )
        return normalized or None

    def to_dict(self) -> dict[str, Any]:
        message: dict[str, Any] = {
            'content': self.content,
            'role': 'assistant',
            'tool_calls': self.tool_calls,
        }
        if self.reasoning_content:
            message['reasoning_content'] = self.reasoning_content
        return {
            'id': self.id,
            'model': self.model,
            'choices': [
                {
                    'message': message,
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

    False for Google-family models on OpenAI-compatible proxies -- Google
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
    degrade silently -- callers should warn.
    """


def _resolve_transport_profile(
    model_family: str | None,
    base_url: str | None,
) -> TransportProfile:
    """Resolve transport capabilities for an OpenAI-compatible client.

    The decision combines the **model family** (queried via
    :func:`backend.inference.capabilities.provider_capabilities.get_provider_capabilities`
    so adding a new provider quirk only touches the registry) with the
    transport URL. Native SDK clients (``AnthropicClient``, ``GeminiClient``)
    don't need this -- they speak their own protocol natively.

    Args:
        model_family: Provider that owns the model (e.g. ``"openai"``,
            ``"google"``, ``"anthropic"``, ``"deepseek"``). Comes from
            ``resolve_provider()``.
        base_url: The endpoint URL being used. ``None`` means the SDK
            default.
    """
    from backend.inference.capabilities.provider_capabilities import (
        get_provider_capabilities,
    )

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
            cleaned.append(_normalize_assistant_tool_calls(msg))
            continue

        if role == 'tool':
            cleaned.append(_normalize_tool_result(msg))
            continue

        cleaned.append(msg)
    return cleaned


def _normalize_assistant_tool_calls(msg: dict[str, Any]) -> dict[str, Any]:
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
    return normalized


def _normalize_tool_result(msg: dict[str, Any]) -> dict[str, Any]:
    tool_name = str(msg.get('name') or 'tool')
    tool_output = _extract_openai_message_text(msg.get('content'))
    return {
        'role': 'user',
        'content': (
            f'[Tool result from {tool_name}]\n{tool_output}'.strip()
            or f'[Tool result from {tool_name}]'
        ),
    }


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
        self,
        prompt_tokens: int,
        completion_tokens: int,
        config: Any | None = None,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
    ) -> float:
        """Calculate completion cost for this client's model."""
        from backend.inference.cost_tracker import get_completion_cost

        return get_completion_cost(
            self.model_name,
            prompt_tokens,
            completion_tokens,
            config,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
        )
