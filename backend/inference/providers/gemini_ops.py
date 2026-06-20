"""Google Gemini client extracted from direct_clients.

This module hosts GeminiClient (559 lines). The parent `direct_clients.py`
re-exports GeminiClient for backward compat (via PEP 562 __getattr__).
"""

from __future__ import annotations

# google-genai subclasses aiohttp.ClientSession; aiohttp emits DeprecationWarning
# while ``_api_client`` is loading. A local catch is reliable regardless of
# PYTHONWARNINGS / filter registration order.
import warnings
from collections.abc import AsyncIterator
from typing import Any, cast

import httpx

with warnings.catch_warnings():
    warnings.simplefilter('ignore', DeprecationWarning)
    from google import genai

from backend.core import json_compat as json
from backend.core.logging.logger import app_logger as logger
from backend.inference.clients import (
    DirectLLMClient,
    LLMResponse,
)
from backend.inference.clients.base import _normalize_timeout_seconds


def _gemini_timeout_ms(timeout: float | int | None) -> int:
    normalized = _normalize_timeout_seconds(timeout)
    if normalized is None:
        return 45000
    return max(1, int(normalized * 1000))


class GeminiClient(DirectLLMClient):
    """Client for Google Gemini."""

    def __init__(
        self, model_name: str, api_key: str, timeout: float | int | None = None
    ):
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

        # Force the SDK onto its httpx async path so it does not instantiate
        # the aiohttp session subclass that emits a DeprecationWarning.
        http_options = HttpOptions(
            timeout=_gemini_timeout_ms(timeout),
            async_client_args={'transport': httpx.AsyncHTTPTransport()},
        )
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
        from backend.inference.caching.prompt_cache import get_prompt_cache

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

    def _map_gemini_rate_limit(self, exc: Any, error_str: str) -> Exception:
        import re

        from backend.inference.exceptions import RateLimitError, RateLimitKind

        kind = RateLimitKind.TPM
        retry_after = None
        delay_match = re.search(
            r'(?:retry in |retryDelay[\'\":\s]*)([0-9.]+)', error_str, re.IGNORECASE
        )
        if delay_match:
            try:
                retry_after = float(delay_match.group(1))
            except (ValueError, TypeError):
                pass
        if 'rpm' in error_str or 'requests per minute' in error_str:
            kind = RateLimitKind.RPM
        elif 'rpd' in error_str or 'requests per day' in error_str:
            kind = RateLimitKind.RPD
        return RateLimitError(
            str(exc),
            llm_provider='google',
            model=self.model_name,
            kind=kind,
            retry_after=retry_after,
        )

    def _map_gemini_bad_request(self, exc: Any, error_str: str) -> Exception:
        from backend.inference.exceptions import (
            BadRequestError,
            ContextWindowExceededError,
            is_context_window_error,
        )

        if is_context_window_error(error_str, exc):
            return ContextWindowExceededError(
                str(exc), llm_provider='google', model=self.model_name
            )
        return BadRequestError(str(exc), llm_provider='google', model=self.model_name)

    def _map_gemini_api_error(self, exc: Any, error_str: str) -> Exception:
        from backend.inference.exceptions import APIError as ProviderAPIError

        mapped = _match_gemini_error(exc, error_str, self)
        if mapped is not None:
            return mapped
        return ProviderAPIError(str(exc), llm_provider='google', model=self.model_name)

    def _map_gemini_error(self, exc: Exception) -> Exception:
        """Map google.genai exceptions to Grinta LLM exceptions."""
        import asyncio

        import aiohttp
        from google.genai.errors import APIError

        from backend.inference.exceptions import APIConnectionError, Timeout

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
        return {'choices': [{'delta': {'content': text}, 'finish_reason': None}]}

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


def _match_gemini_error(exc: Any, error_str: str, client: Any) -> Exception | None:
    from backend.inference.exceptions import (
        AuthenticationError,
        InternalServerError,
        NotFoundError,
        ServiceUnavailableError,
    )

    model = client.model_name

    if client._is_gemini_api_key_error(error_str):
        return AuthenticationError(str(exc), llm_provider='google', model=model)
    if exc.code == 429 or 'quota' in error_str or 'rate limit' in error_str:
        return client._map_gemini_rate_limit(exc, error_str)
    if (
        exc.code in (401,)
        or 'unauthorized' in error_str
        or 'invalid api key' in error_str
    ):
        return AuthenticationError(str(exc), llm_provider='google', model=model)
    if exc.code == 404 or 'not found' in error_str:
        return NotFoundError(str(exc), llm_provider='google', model=model)
    if (
        exc.code in (500, 502, 503, 504)
        or 'unavailable' in error_str
        or 'overloaded' in error_str
    ):
        return ServiceUnavailableError(str(exc), llm_provider='google', model=model)
    if exc.code == 400:
        return client._map_gemini_bad_request(exc, error_str)
    if exc.code and exc.code >= 500:
        return InternalServerError(str(exc), llm_provider='google', model=model)
    return None
