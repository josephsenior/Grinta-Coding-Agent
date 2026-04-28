"""Anthropic provider operations for DirectLLMClient wrappers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any


def extract_anthropic_tool_calls(
    content_blocks: list,
) -> tuple[str, list[dict[str, Any]] | None]:
    from backend.inference.mappers.anthropic import extract_tool_calls

    return extract_tool_calls(content_blocks)


def prepare_anthropic_kwargs(
    client: Any, messages: list[dict[str, Any]], kwargs: dict[str, Any]
) -> tuple[list, dict[str, Any]]:
    from backend.inference.mappers.anthropic import prepare_kwargs

    return prepare_kwargs(messages, kwargs, client.model_name)


def map_anthropic_error(client: Any, exc: Exception) -> Exception:
    import anthropic
    import httpx

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
        return Timeout(str(exc), llm_provider='anthropic', model=client.model_name)
    if isinstance(exc, (anthropic.APIConnectionError, httpx.RequestError)):
        return APIConnectionError(
            str(exc), llm_provider='anthropic', model=client.model_name
        )
    if isinstance(exc, anthropic.RateLimitError):
        return RateLimitError(
            str(exc), llm_provider='anthropic', model=client.model_name
        )
    if isinstance(exc, anthropic.AuthenticationError):
        return AuthenticationError(
            str(exc), llm_provider='anthropic', model=client.model_name
        )
    if isinstance(exc, anthropic.BadRequestError):
        error_str = str(exc).lower()
        if is_context_window_error(error_str, exc):
            return ContextWindowExceededError(
                str(exc), llm_provider='anthropic', model=client.model_name
            )
        return BadRequestError(
            str(exc), llm_provider='anthropic', model=client.model_name
        )
    if isinstance(exc, anthropic.NotFoundError):
        return NotFoundError(
            str(exc), llm_provider='anthropic', model=client.model_name
        )
    if isinstance(exc, anthropic.InternalServerError):
        return InternalServerError(
            str(exc), llm_provider='anthropic', model=client.model_name
        )
    if isinstance(exc, anthropic.APIStatusError):
        return ProviderAPIError(
            str(exc),
            llm_provider='anthropic',
            model=client.model_name,
            status_code=exc.status_code,
        )
    return exc


def completion(client: Any, messages: list[dict[str, Any]], **kwargs) -> Any:
    from backend.inference import direct_clients as dc

    filtered, kwargs = client._prepare_anthropic_kwargs(messages, kwargs)
    model = kwargs.pop('model', client.model_name)
    try:
        response = client.client.messages.create(
            model=model,
            messages=filtered,  # type: ignore[arg-type]
            **kwargs,
        )
    except Exception as e:
        raise client._map_anthropic_error(e) from e
    content, tool_calls = client._extract_anthropic_tool_calls(response.content)
    return dc.LLMResponse(
        content=content,
        model=response.model,
        usage={
            'prompt_tokens': response.usage.input_tokens,
            'completion_tokens': response.usage.output_tokens,
            'total_tokens': response.usage.input_tokens + response.usage.output_tokens,
        },
        id=response.id,
        finish_reason=response.stop_reason or 'stop',
        tool_calls=tool_calls,
    )


async def acompletion(client: Any, messages: list[dict[str, Any]], **kwargs) -> Any:
    from backend.inference import direct_clients as dc

    filtered, kwargs = client._prepare_anthropic_kwargs(messages, kwargs)
    model = kwargs.pop('model', client.model_name)
    try:
        response = await client.async_client.messages.create(
            model=model,
            messages=filtered,  # type: ignore[arg-type]
            **kwargs,
        )
    except Exception as e:
        raise client._map_anthropic_error(e) from e
    content, tool_calls = client._extract_anthropic_tool_calls(response.content)
    return dc.LLMResponse(
        content=content,
        model=response.model,
        usage={
            'prompt_tokens': response.usage.input_tokens,
            'completion_tokens': response.usage.output_tokens,
            'total_tokens': response.usage.input_tokens + response.usage.output_tokens,
        },
        id=response.id,
        finish_reason=response.stop_reason or 'stop',
        tool_calls=tool_calls,
    )


async def astream(
    client: Any, messages: list[dict[str, Any]], **kwargs
) -> AsyncIterator[dict[str, Any]]:
    from backend.inference.mappers.anthropic import _apply_system_cache_control

    system_raw = next((m['content'] for m in messages if m['role'] == 'system'), None)
    filtered_messages = [m for m in messages if m['role'] != 'system']

    if 'model' not in kwargs:
        kwargs['model'] = client.model_name

    system_msg = _apply_system_cache_control(
        system_raw, kwargs.get('model', client.model_name), kwargs
    )

    try:
        async with client.async_client.messages.stream(
            messages=filtered_messages,  # type: ignore[arg-type]
            system=system_msg,  # type: ignore[arg-type]
            **kwargs,
        ) as stream:
            input_tokens = 0
            output_tokens = 0
            async for event in stream:
                if event.type == 'message_start':
                    usage = getattr(getattr(event, 'message', None), 'usage', None)
                    if usage is not None:
                        input_tokens = int(getattr(usage, 'input_tokens', 0) or 0)
                elif event.type == 'message_delta':
                    delta_usage = getattr(event, 'usage', None)
                    if delta_usage is not None:
                        output_tokens = int(
                            getattr(delta_usage, 'output_tokens', 0) or 0
                        )
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
                elif (
                    event.type == 'content_block_delta'
                    and event.delta.type == 'thinking_delta'
                ):
                    yield {
                        'choices': [
                            {
                                'delta': {
                                    'reasoning_content': getattr(
                                        event.delta, 'thinking', ''
                                    )
                                },
                                'finish_reason': None,
                            }
                        ]
                    }
                elif event.type == 'content_block_delta':
                    yield {
                        'choices': [
                            {
                                'delta': {'content': getattr(event.delta, 'text', '')},
                                'finish_reason': None,
                            }
                        ]
                    }
                elif event.type == 'message_stop':
                    if input_tokens or output_tokens:
                        yield {
                            'choices': [],
                            'usage': {
                                'prompt_tokens': input_tokens,
                                'completion_tokens': output_tokens,
                                'total_tokens': input_tokens + output_tokens,
                            },
                        }
                    yield {'choices': [{'delta': {}, 'finish_reason': 'stop'}]}
    except Exception as e:
        raise client._map_anthropic_error(e) from e