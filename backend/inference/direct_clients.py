"""Direct LLM clients for OpenAI, Anthropic, Google Gemini, and xAI Grok.

This module provides direct SDK integrations with major LLM providers,
offering a lightweight and stable alternative to multi-provider abstraction libraries.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any, cast

import httpx
from anthropic import Anthropic, AsyncAnthropic
from google import genai
from openai import AsyncOpenAI, OpenAI

from backend.core import json_compat as json
from backend.core.logger import app_logger as logger

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
    return f'{provider}::{base_url or "default"}'


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
                    timeout=httpx.Timeout(timeout=600.0, connect=10.0),
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
        **kwargs,
    ):
        self.content = content
        self.model = model
        self.usage = usage
        self.id = kwargs.get('response_id', kwargs.get('id', response_id))
        self.finish_reason = self._normalize_finish_reason(finish_reason)
        self.tool_calls = self._normalize_tool_calls(tool_calls)

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
        supports_request_metadata: bool = True,
    ):
        self._model_name = model_name
        self._supports_request_metadata = supports_request_metadata
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
        from backend.inference.mappers.openai import extract_tool_calls

        return extract_tool_calls(message)

    def _map_openai_error(self, exc: Exception) -> Exception:
        """Map openai SDK exceptions to App LLM exceptions."""
        import openai

        from backend.inference.exceptions import (
            APIConnectionError,
            AuthenticationError,
            BadRequestError,
            ContextWindowExceededError,
            InternalServerError,
            NotFoundError,
            RateLimitError,
            Timeout,
            is_context_window_error,
        )
        from backend.inference.exceptions import (
            APIError as ProviderAPIError,
        )

        if isinstance(exc, (openai.APITimeoutError, httpx.TimeoutException)):
            return Timeout(str(exc), llm_provider='openai', model=self.model_name)
        if isinstance(exc, (openai.APIConnectionError, httpx.RequestError)):
            return APIConnectionError(
                str(exc), llm_provider='openai', model=self.model_name
            )
        if isinstance(exc, openai.RateLimitError):
            # OpenAI uses HTTP 429 for both transient rate limits and non-transient
            # "insufficient_quota" (billing/credits). The latter should NOT be retried.
            code = getattr(exc, 'code', None)
            message = str(exc)

            # The OpenAI SDK may not surface the provider error code directly
            # on the exception, but it typically includes a parsed response body.
            body = getattr(exc, 'body', None)
            if not code and isinstance(body, dict):
                err = body.get('error')
                if isinstance(err, dict):
                    code = err.get('code') or err.get('type') or code
                    body_msg = err.get('message')
                    if isinstance(body_msg, str) and body_msg:
                        message = body_msg

            lowered = message.lower()
            status_code = getattr(exc, 'status_code', None) or 429
            if isinstance(code, str) and code and f'code={code}' not in message:
                message = f'{message} (code={code})'

            if code == 'insufficient_quota' or 'insufficient_quota' in lowered:
                return AuthenticationError(
                    message,
                    llm_provider='openai',
                    model=self.model_name,
                    status_code=status_code,
                    code=code,
                    body=body,
                )
            return RateLimitError(
                message,
                llm_provider='openai',
                model=self.model_name,
                status_code=status_code,
                code=code,
                body=body,
            )
        if isinstance(exc, openai.AuthenticationError):
            return AuthenticationError(
                str(exc), llm_provider='openai', model=self.model_name
            )
        if isinstance(exc, openai.BadRequestError):
            error_str = str(exc).lower()
            if is_context_window_error(error_str, exc):
                return ContextWindowExceededError(
                    str(exc), llm_provider='openai', model=self.model_name
                )
            return BadRequestError(
                str(exc), llm_provider='openai', model=self.model_name
            )
        if isinstance(exc, openai.NotFoundError):
            return NotFoundError(str(exc), llm_provider='openai', model=self.model_name)
        if isinstance(exc, openai.InternalServerError):
            return InternalServerError(
                str(exc), llm_provider='openai', model=self.model_name
            )
        if isinstance(exc, openai.APIStatusError):
            return ProviderAPIError(
                str(exc),
                llm_provider='openai',
                model=self.model_name,
                status_code=exc.status_code,
            )
        return exc

    def _strip_unsupported_params(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Remove request parameters not supported by this provider."""
        if not self._supports_request_metadata:
            extra_body = kwargs.get('extra_body')
            if isinstance(extra_body, dict) and 'metadata' in extra_body:
                extra_body = {k: v for k, v in extra_body.items() if k != 'metadata'}
                if extra_body:
                    kwargs = {**kwargs, 'extra_body': extra_body}
                else:
                    kwargs = {k: v for k, v in kwargs.items() if k != 'extra_body'}
        return kwargs

    def _clean_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Remove OpenAI-specific fields from messages for providers that don't support them."""
        if self._supports_request_metadata:
            return messages
        cleaned = []
        for msg in messages:
            if isinstance(msg, dict) and 'tool_ok' in msg:
                msg = {k: v for k, v in msg.items() if k != 'tool_ok'}
            cleaned.append(msg)
        return cleaned

    def completion(self, messages: list[dict[str, Any]], **kwargs) -> LLMResponse:
        from backend.inference.mappers.openai import (
            strip_prompt_cache_hints_from_messages,
        )

        messages = strip_prompt_cache_hints_from_messages(messages)
        messages = self._clean_messages(messages)
        kwargs = _sanitize_openai_compatible_kwargs(kwargs)
        kwargs = self._strip_unsupported_params(kwargs)
        kwargs['model'] = self.model_name
        try:
            response = self.client.chat.completions.create(
                messages=messages,  # type: ignore[arg-type]
                **kwargs,
            )
        except Exception as e:
            raise self._map_openai_error(e) from e
        if not getattr(response, 'choices', None) or len(response.choices) == 0:
            from backend.inference.exceptions import BadRequestError

            raise BadRequestError(
                'OpenAI completion returned no choices',
                llm_provider='openai',
                model=self.model_name,
            )
        first = response.choices[0]
        msg = first.message
        tool_calls = self._extract_openai_tool_calls(msg)

        # Some OpenAI-compatible APIs (or parameter combos) can yield a response
        # where `content` is empty and no tool call is present. This is almost
        # always a provider-side anomaly, so capture enough context to debug.
        content_value = getattr(msg, 'content', None)
        if (
            content_value is None
            or (isinstance(content_value, str) and not content_value.strip())
        ) and not tool_calls:
            try:
                msg_dump = msg.model_dump() if hasattr(msg, 'model_dump') else str(msg)
            except Exception:
                msg_dump = str(msg)
            logger.warning(
                'OpenAI-compatible completion returned empty message (no tool calls). '
                'model=%s finish_reason=%s msg=%s',
                self.model_name,
                getattr(first, 'finish_reason', None),
                msg_dump,
            )
        return LLMResponse(
            content=msg.content or '',
            model=response.model,
            usage={
                'prompt_tokens': response.usage.prompt_tokens if response.usage else 0,
                'completion_tokens': response.usage.completion_tokens
                if response.usage
                else 0,
                'total_tokens': response.usage.total_tokens if response.usage else 0,
            },
            id=response.id,
            finish_reason=getattr(first, 'finish_reason', None) or '',
            tool_calls=tool_calls,
        )

    async def acompletion(
        self, messages: list[dict[str, Any]], **kwargs
    ) -> LLMResponse:
        from backend.inference.mappers.openai import (
            strip_prompt_cache_hints_from_messages,
        )

        messages = strip_prompt_cache_hints_from_messages(messages)
        messages = self._clean_messages(messages)
        kwargs = _sanitize_openai_compatible_kwargs(kwargs)
        kwargs = self._strip_unsupported_params(kwargs)
        kwargs.pop('model', None)
        try:
            response = await self.async_client.chat.completions.create(
                model=self.model_name,
                messages=messages,  # type: ignore[arg-type]
                **kwargs,
            )
        except Exception as e:
            raise self._map_openai_error(e) from e
        if not getattr(response, 'choices', None) or len(response.choices) == 0:
            from backend.inference.exceptions import BadRequestError

            raise BadRequestError(
                'OpenAI completion returned no choices',
                llm_provider='openai',
                model=self.model_name,
            )
        first = response.choices[0]
        msg = first.message
        tool_calls = self._extract_openai_tool_calls(msg)
        return LLMResponse(
            content=msg.content or '',
            model=response.model,
            usage={
                'prompt_tokens': response.usage.prompt_tokens if response.usage else 0,
                'completion_tokens': response.usage.completion_tokens
                if response.usage
                else 0,
                'total_tokens': response.usage.total_tokens if response.usage else 0,
            },
            id=response.id,
            finish_reason=getattr(first, 'finish_reason', None) or '',
            tool_calls=tool_calls,
        )

    async def astream(
        self, messages: list[dict[str, Any]], **kwargs
    ) -> AsyncIterator[dict[str, Any]]:
        from backend.inference.mappers.openai import (
            strip_prompt_cache_hints_from_messages,
        )

        messages = strip_prompt_cache_hints_from_messages(messages)
        messages = self._clean_messages(messages)
        kwargs = _sanitize_openai_compatible_kwargs(kwargs)
        kwargs = self._strip_unsupported_params(kwargs)
        # OpenAI-compatible APIs require stream=True for token streaming.
        kwargs['stream'] = True
        kwargs.pop('model', None)
        try:
            stream = await self.async_client.chat.completions.create(
                model=self.model_name,
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
        from backend.inference.mappers.anthropic import extract_tool_calls

        return extract_tool_calls(content_blocks)

    def _prepare_anthropic_kwargs(
        self, messages: list[dict[str, Any]], kwargs: dict[str, Any]
    ) -> tuple[list, dict[str, Any]]:
        from backend.inference.mappers.anthropic import prepare_kwargs

        return prepare_kwargs(messages, kwargs, self.model_name)

    def _map_anthropic_error(self, exc: Exception) -> Exception:
        """Map anthropic SDK exceptions to App LLM exceptions."""
        import anthropic

        from backend.inference.exceptions import (
            APIConnectionError,
            AuthenticationError,
            BadRequestError,
            ContextWindowExceededError,
            InternalServerError,
            NotFoundError,
            RateLimitError,
            Timeout,
            is_context_window_error,
        )
        from backend.inference.exceptions import (
            APIError as ProviderAPIError,
        )

        if isinstance(exc, (anthropic.APITimeoutError, httpx.TimeoutException)):
            return Timeout(str(exc), llm_provider='anthropic', model=self.model_name)
        if isinstance(exc, (anthropic.APIConnectionError, httpx.RequestError)):
            return APIConnectionError(
                str(exc), llm_provider='anthropic', model=self.model_name
            )
        if isinstance(exc, anthropic.RateLimitError):
            return RateLimitError(
                str(exc), llm_provider='anthropic', model=self.model_name
            )
        if isinstance(exc, anthropic.AuthenticationError):
            return AuthenticationError(
                str(exc), llm_provider='anthropic', model=self.model_name
            )
        if isinstance(exc, anthropic.BadRequestError):
            error_str = str(exc).lower()
            if is_context_window_error(error_str, exc):
                return ContextWindowExceededError(
                    str(exc), llm_provider='anthropic', model=self.model_name
                )
            return BadRequestError(
                str(exc), llm_provider='anthropic', model=self.model_name
            )
        if isinstance(exc, anthropic.NotFoundError):
            return NotFoundError(
                str(exc), llm_provider='anthropic', model=self.model_name
            )
        if isinstance(exc, anthropic.InternalServerError):
            return InternalServerError(
                str(exc), llm_provider='anthropic', model=self.model_name
            )
        if isinstance(exc, anthropic.APIStatusError):
            return ProviderAPIError(
                str(exc),
                llm_provider='anthropic',
                model=self.model_name,
                status_code=exc.status_code,
            )
        return exc

    def completion(self, messages: list[dict[str, Any]], **kwargs) -> LLMResponse:
        filtered, kwargs = self._prepare_anthropic_kwargs(messages, kwargs)
        model = kwargs.pop('model', self.model_name)
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
                'prompt_tokens': response.usage.input_tokens,
                'completion_tokens': response.usage.output_tokens,
                'total_tokens': response.usage.input_tokens
                + response.usage.output_tokens,
            },
            id=response.id,
            finish_reason=response.stop_reason or 'stop',
            tool_calls=tool_calls,
        )

    async def acompletion(
        self, messages: list[dict[str, Any]], **kwargs
    ) -> LLMResponse:
        filtered, kwargs = self._prepare_anthropic_kwargs(messages, kwargs)
        model = kwargs.pop('model', self.model_name)
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
                'prompt_tokens': response.usage.input_tokens,
                'completion_tokens': response.usage.output_tokens,
                'total_tokens': response.usage.input_tokens
                + response.usage.output_tokens,
            },
            id=response.id,
            finish_reason=response.stop_reason or 'stop',
            tool_calls=tool_calls,
        )

    async def astream(
        self, messages: list[dict[str, Any]], **kwargs
    ) -> AsyncIterator[dict[str, Any]]:
        from backend.inference.mappers.anthropic import _apply_system_cache_control

        system_raw = next(
            (m['content'] for m in messages if m['role'] == 'system'), None
        )
        filtered_messages = [m for m in messages if m['role'] != 'system']

        if 'model' not in kwargs:
            kwargs['model'] = self.model_name

        system_msg = _apply_system_cache_control(
            system_raw, kwargs.get('model', self.model_name), kwargs
        )

        try:
            async with self.async_client.messages.stream(
                messages=filtered_messages,  # type: ignore[arg-type]
                system=system_msg,  # type: ignore[arg-type]
                **kwargs,
            ) as stream:
                async for event in stream:
                    # Convert Anthropic events to OpenAI-like chunks for compatibility
                    if (
                        event.type == 'content_block_start'
                        and event.content_block.type == 'tool_use'
                    ):
                        yield {
                            'choices': [
                                {
                                    'delta': {
                                        'tool_calls': [
                                            {
                                                'index': event.index,
                                                'id': event.content_block.id,
                                                'type': 'function',
                                                'function': {
                                                    'name': event.content_block.name,
                                                    'arguments': '',
                                                },
                                            }
                                        ]
                                    },
                                    'finish_reason': None,
                                }
                            ]
                        }
                    elif (
                        event.type == 'content_block_delta'
                        and event.delta.type == 'input_json_delta'
                    ):
                        yield {
                            'choices': [
                                {
                                    'delta': {
                                        'tool_calls': [
                                            {
                                                'index': event.index,
                                                'function': {
                                                    'arguments': getattr(
                                                        event.delta, 'partial_json', ''
                                                    )
                                                },
                                            }
                                        ]
                                    },
                                    'finish_reason': None,
                                }
                            ]
                        }
                    elif event.type == 'content_block_delta':
                        yield {
                            'choices': [
                                {
                                    'delta': {
                                        'content': getattr(event.delta, 'text', '')
                                    },  # type: ignore[union-attr]
                                    'finish_reason': None,
                                }
                            ]
                        }
                    elif event.type == 'message_stop':
                        yield {'choices': [{'delta': {}, 'finish_reason': 'stop'}]}
        except Exception as e:
            raise self._map_anthropic_error(e) from e


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

        http_options = HttpOptions(timeout=120000)  # 2 minutes
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
        from backend.inference.gemini_cache import gemini_cache_manager

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

        logger.error('=' * 80)
        logger.error('GOOGLE GENAI EXCEPTION: %s %s', type(exc), exc)
        if hasattr(exc, 'code'):
            logger.error('CODE: %s', exc.code)
        if hasattr(exc, 'message'):
            logger.error('MESSAGE: %s', exc.message)
        if hasattr(exc, 'details'):
            logger.error('DETAILS: %s', exc.details)
        logger.error('=' * 80)

        if isinstance(exc, (asyncio.TimeoutError, httpx.TimeoutException)):
            return Timeout(str(exc), llm_provider='google', model=self.model_name)
        if isinstance(exc, (aiohttp.ClientError, httpx.RequestError)):
            return APIConnectionError(
                str(exc), llm_provider='google', model=self.model_name
            )

        if isinstance(exc, APIError):
            error_str = str(exc).lower()

            # Google Gemini sometimes returns 400 INVALID_ARGUMENT for invalid/unknown keys
            # (e.g., "API Key not found"), and the message can contain "not found" which
            # would otherwise be misclassified as a 404.
            if 'api key' in error_str and (
                'not found' in error_str
                or 'invalid api key' in error_str
                or 'api_key_invalid' in error_str
            ):
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
        return exc

    def completion(self, messages: list[dict[str, Any]], **kwargs) -> LLMResponse:
        from backend.inference.mappers.gemini import (
            ensure_non_empty_content,
            extract_text,
            extract_tool_calls,
            gemini_usage,
        )

        model_name, gen_cfg, system_instruction, history, prompt, tools, cache_name = (
            self._build_gemini_chat(messages, kwargs)
        )

        config: Any = {
            **gen_cfg,
            'tools': tools,
        }
        if cache_name:
            config['cached_content'] = cache_name
        else:
            config['system_instruction'] = system_instruction

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
        )

    async def acompletion(
        self, messages: list[dict[str, Any]], **kwargs
    ) -> LLMResponse:
        """Asynchronous completion."""
        from backend.inference.mappers.gemini import (
            ensure_non_empty_content,
            extract_text,
            extract_tool_calls,
            gemini_usage,
        )

        model_name, gen_cfg, system_instruction, history, prompt, tools, cache_name = (
            self._build_gemini_chat(messages, kwargs)
        )

        config: Any = {
            **gen_cfg,
            'tools': tools,
        }
        if cache_name:
            config['cached_content'] = cache_name
        else:
            config['system_instruction'] = system_instruction

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
            'tools': tools,
        }
        if cache_name:
            config['cached_content'] = cache_name
        else:
            config['system_instruction'] = system_instruction

        logger.debug('Gemini config: %s', config)

        chat = self.client.aio.chats.create(
            model=model_name,
            config=config,
            history=cast(Any, history),
        )

        try:
            stream = await chat.send_message_stream(prompt, **kwargs)
            # Use a global counter across all chunks so that function calls
            # arriving in separate streaming chunks (one call per chunk) get
            # unique indices rather than all defaulting to 0 via enumerate().
            fc_idx_counter = 0
            async for chunk in stream:
                fcs = getattr(chunk, 'function_calls', None)
                if fcs:
                    for fc in fcs:
                        try:
                            _args = getattr(fc, 'args', {})
                            if hasattr(type(fc), 'to_dict') and _args:
                                _to_dict = getattr(type(fc), 'to_dict')
                                if callable(_to_dict):
                                    args_dict = _to_dict(_args)
                                else:
                                    args_dict = _args
                            elif hasattr(_args, 'items'):
                                args_dict = dict(_args.items())  # type: ignore[union-attr]
                            elif hasattr(_args, '__dict__'):
                                args_dict = _args.__dict__
                            else:
                                args_dict = _args

                            if hasattr(args_dict, 'pb') and hasattr(args_dict, 'items'):
                                args_dict = dict(args_dict.items())  # type: ignore[union-attr]

                            if isinstance(args_dict, dict):
                                args_str = json.dumps(
                                    args_dict,
                                    ensure_ascii=False,
                                    separators=(',', ':'),
                                )
                            else:
                                args_str = json.dumps(
                                    getattr(fc, 'args', {}),
                                    ensure_ascii=False,
                                    separators=(',', ':'),
                                )
                        except Exception:
                            args_str = '{}'
                        yield {
                            'choices': [
                                {
                                    'delta': {
                                        'tool_calls': [
                                            {
                                                'index': fc_idx_counter,
                                                'id': f'call_{fc.name}_{fc_idx_counter}',
                                                'type': 'function',
                                                'function': {
                                                    'name': fc.name,
                                                    'arguments': args_str,
                                                },
                                            }
                                        ]
                                    },
                                    'finish_reason': None,
                                }
                            ]
                        }
                        fc_idx_counter += 1
                text = chunk.text or ''
                if text:
                    yield {
                        'choices': [{'delta': {'content': text}, 'finish_reason': None}]
                    }
        except Exception as e:
            raise self._map_gemini_error(e) from e
        yield {'choices': [{'delta': {}, 'finish_reason': 'stop'}]}


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

    # Route to appropriate client based on provider
    if provider == 'anthropic':
        return AnthropicClient(model_name=stripped_model, api_key=api_key)

    if provider == 'google':
        return GeminiClient(model_name=stripped_model, api_key=api_key)

    if provider == 'openhands':
        return OpenAIClient(
            model_name=f'litellm_proxy/{stripped_model}',
            api_key=api_key,
            base_url=resolved_base_url,
            supports_request_metadata=False,
        )

    # All OpenAI-compatible providers use OpenAI client
    # (OpenAI, xAI, DeepSeek, Mistral, Ollama, LM Studio, vLLM, etc.)
    # Only the real OpenAI API supports the `metadata` request field; all other
    # compatible providers (Groq, Mistral, etc.) reject it with a 400 error.
    return OpenAIClient(
        model_name=stripped_model,
        api_key=api_key,
        base_url=resolved_base_url,
        supports_request_metadata=(provider == 'openai'),
    )
