"""OpenAI-compatible provider operations for DirectLLMClient wrappers."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import Any


def extract_openai_http_status(exc: Exception) -> int | None:
    """Best-effort HTTP status from an OpenAI SDK (or compatible) exception.

    Gateways sometimes return **401** with a plain-text body ``Unauthorized``.
    The Python SDK then fails JSON decoding and may surface the failure as
    ``InternalServerError`` with ``status code: 401`` embedded in ``str(exc)``
    instead of ``AuthenticationError``. This helper recovers the status so we can
    map to :class:`~backend.inference.exceptions.AuthenticationError` and avoid
    treating auth failures as retryable server errors.
    """
    code = getattr(exc, 'status_code', None)
    if isinstance(code, int) and 100 <= code <= 599:
        return code
    response = getattr(exc, 'response', None)
    if response is not None:
        sc = getattr(response, 'status_code', None)
        if isinstance(sc, int) and 100 <= sc <= 599:
            return sc
    try:
        text = str(exc)
    except Exception:
        return None
    m = re.search(r'status code:\s*(\d{3})\b', text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None  # type: ignore[unreachable]


def simplify_openai_unauthorized_message(exc: Exception, status_code: int) -> str:
    """User-facing text for 401/403; drops misleading JSON-decode noise."""
    try:
        raw = str(exc)
    except Exception:
        raw = f'{type(exc).__name__} (unprintable exception)'
    if status_code != 401:
        return raw
    low = raw.lower()
    if 'invalid character' in low and (
        'unauthorized' in low or 'body: unauthorized' in low
    ):
        return (
            'HTTP 401 Unauthorized: the API rejected this request (missing key, wrong key, '
            'key for another provider, or llm_base_url does not match that provider). '
            'The server returned plain text instead of JSON—the '
            '"invalid character \'U\'" / JSON parse line is an artifact from the word '
            '"Unauthorized", not a typo in your API key.'
        )
    return raw


def extract_openai_tool_calls(message: Any) -> list[dict[str, Any]] | None:
    from backend.inference.mappers.openai import extract_tool_calls

    return extract_tool_calls(message)


def _map_html_api_error(client: Any, exc: Exception, raw_msg: str) -> Exception:
    from backend.inference.exceptions import (
        AuthenticationError,
        BadRequestError,
        format_html_api_error_response,
    )

    friendly = format_html_api_error_response(
        raw_msg,
        base_url=client._api_base_url,
        model=client.model_name,
    )
    status_code = getattr(exc, 'status_code', None)
    if status_code in (401, 403):
        return AuthenticationError(
            friendly,
            llm_provider='openai',
            model=client.model_name,
            status_code=status_code,
        )
    return BadRequestError(
        friendly,
        llm_provider='openai',
        model=client.model_name,
    )


def _rate_limit_error_details(exc: Exception) -> tuple[str, Any, Any, int]:
    code = getattr(exc, 'code', None)
    message = str(exc)
    body = getattr(exc, 'body', None)
    if not code and isinstance(body, dict):
        err = body.get('error')
        if isinstance(err, dict):
            code = err.get('code') or err.get('type') or code
            body_msg = err.get('message')
            if isinstance(body_msg, str) and body_msg:
                message = body_msg

    status_code = getattr(exc, 'status_code', None) or 429
    if isinstance(code, str) and code and f'code={code}' not in message:
        message = f'{message} (code={code})'
    return message, code, body, status_code


def _map_rate_limit_error(client: Any, exc: Exception) -> Exception:
    from backend.inference.exceptions import AuthenticationError, RateLimitError
    from backend.inference.rate_limit_parser import enrich_rate_limit_exception

    message, code, body, status_code = _rate_limit_error_details(exc)
    lowered = message.lower()
    if code == 'insufficient_quota' or 'insufficient_quota' in lowered:
        return AuthenticationError(
            message,
            llm_provider='openai',
            model=client.model_name,
            status_code=status_code,
            code=code,
            body=body,
        )
    mapped = RateLimitError(
        message,
        llm_provider='openai',
        model=client.model_name,
        status_code=status_code,
        code=code,
        body=body,
    )
    return enrich_rate_limit_exception(exc, mapped)


def _map_bad_request_error(client: Any, exc: Exception) -> Exception:
    from backend.inference.exceptions import (
        BadRequestError,
        ContextWindowExceededError,
        is_context_window_error,
    )

    error_str = str(exc).lower()
    if is_context_window_error(error_str, exc):
        return ContextWindowExceededError(
            str(exc),
            llm_provider='openai',
            model=client.model_name,
        )
    return BadRequestError(
        str(exc),
        llm_provider='openai',
        model=client.model_name,
    )


def map_openai_error(client: Any, exc: Exception) -> Exception:
    import httpx
    import openai

    from backend.inference.exceptions import (
        APIConnectionError,
        AuthenticationError,
        InternalServerError,
        NotFoundError,
        Timeout,
        is_html_api_body,
    )
    from backend.inference.exceptions import (
        APIError as ProviderAPIError,
    )

    raw_msg = str(exc)
    if is_html_api_body(raw_msg):
        return _map_html_api_error(client, exc, raw_msg)

    status_from_wire = extract_openai_http_status(exc)
    if status_from_wire in (401, 403):
        return AuthenticationError(
            simplify_openai_unauthorized_message(exc, status_from_wire),
            llm_provider='openai',
            model=client.model_name,
            status_code=status_from_wire,
        )

    if isinstance(exc, (openai.APITimeoutError, httpx.TimeoutException)):
        return Timeout(str(exc), llm_provider='openai', model=client.model_name)
    if isinstance(exc, (openai.APIConnectionError, httpx.RequestError)):
        return APIConnectionError(
            str(exc), llm_provider='openai', model=client.model_name
        )
    if isinstance(exc, openai.RateLimitError):
        return _map_rate_limit_error(client, exc)
    if isinstance(exc, openai.AuthenticationError):
        return AuthenticationError(
            str(exc), llm_provider='openai', model=client.model_name
        )
    if isinstance(exc, openai.BadRequestError):
        return _map_bad_request_error(client, exc)
    if isinstance(exc, openai.NotFoundError):
        return NotFoundError(str(exc), llm_provider='openai', model=client.model_name)
    if isinstance(exc, openai.InternalServerError):
        return InternalServerError(
            str(exc), llm_provider='openai', model=client.model_name
        )
    if isinstance(exc, openai.APIStatusError):
        return ProviderAPIError(
            str(exc),
            llm_provider='openai',
            model=client.model_name,
            status_code=exc.status_code,
        )
    return exc


def strip_unsupported_params(profile: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
    if not profile.supports_request_metadata:
        extra_body = kwargs.get('extra_body')
        if isinstance(extra_body, dict) and 'metadata' in extra_body:
            extra_body = {k: v for k, v in extra_body.items() if k != 'metadata'}
            if extra_body:
                kwargs = {**kwargs, 'extra_body': extra_body}
            else:
                kwargs = {k: v for k, v in kwargs.items() if k != 'extra_body'}
    return kwargs


def clean_messages(
    profile: Any, messages: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    from backend.inference import direct_clients as dc

    cleaned = []
    for msg in messages:
        if isinstance(msg, dict) and 'tool_ok' in msg:
            msg = {k: v for k, v in msg.items() if k != 'tool_ok'}
        cleaned.append(msg)
    if not profile.supports_tool_replay or profile.flatten_tool_history:
        return dc._normalize_cross_family_tool_messages(cleaned)
    return cleaned


def completion(client: Any, messages: list[dict[str, Any]], **kwargs) -> Any:
    from backend.inference import direct_clients as dc
    from backend.inference.exceptions import BadRequestError
    from backend.inference.mappers.openai import strip_prompt_cache_hints_from_messages

    messages = strip_prompt_cache_hints_from_messages(messages)
    messages = client._clean_messages(messages)
    kwargs = dc._sanitize_openai_compatible_kwargs(kwargs)
    kwargs = client._strip_unsupported_params(kwargs)
    kwargs['model'] = client.model_name
    try:
        response = client.client.chat.completions.create(
            messages=messages,  # type: ignore[arg-type]
            **kwargs,
        )
    except Exception as e:
        raise client._map_openai_error(e) from e
    if not getattr(response, 'choices', None) or len(response.choices) == 0:
        raise BadRequestError(
            'OpenAI completion returned no choices',
            llm_provider='openai',
            model=client.model_name,
        )
    first = response.choices[0]
    msg = first.message
    tool_calls = client._extract_openai_tool_calls(msg)

    content_value = getattr(msg, 'content', None)
    if (
        content_value is None
        or (isinstance(content_value, str) and not content_value.strip())
    ) and not tool_calls:
        try:
            msg_dump = msg.model_dump() if hasattr(msg, 'model_dump') else str(msg)
        except Exception:
            msg_dump = str(msg)
        dc.logger.warning(
            'OpenAI-compatible completion returned empty message (no tool calls). '
            'model=%s finish_reason=%s msg=%s',
            client.model_name,
            getattr(first, 'finish_reason', None),
            msg_dump,
        )
    return dc.LLMResponse(
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


async def acompletion(client: Any, messages: list[dict[str, Any]], **kwargs) -> Any:
    from backend.inference import direct_clients as dc
    from backend.inference.exceptions import BadRequestError
    from backend.inference.mappers.openai import strip_prompt_cache_hints_from_messages

    messages = strip_prompt_cache_hints_from_messages(messages)
    messages = client._clean_messages(messages)
    kwargs = dc._sanitize_openai_compatible_kwargs(kwargs)
    kwargs = client._strip_unsupported_params(kwargs)
    kwargs.pop('model', None)
    try:
        response = await client.async_client.chat.completions.create(
            model=client.model_name,
            messages=messages,  # type: ignore[arg-type]
            **kwargs,
        )
    except Exception as e:
        raise client._map_openai_error(e) from e
    if not getattr(response, 'choices', None) or len(response.choices) == 0:
        raise BadRequestError(
            'OpenAI completion returned no choices',
            llm_provider='openai',
            model=client.model_name,
        )
    first = response.choices[0]
    msg = first.message
    tool_calls = client._extract_openai_tool_calls(msg)
    return dc.LLMResponse(
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
    client: Any, messages: list[dict[str, Any]], **kwargs
) -> AsyncIterator[dict[str, Any]]:
    from backend.inference import direct_clients as dc
    from backend.inference.mappers.openai import strip_prompt_cache_hints_from_messages

    messages = strip_prompt_cache_hints_from_messages(messages)
    messages = client._clean_messages(messages)
    kwargs = dc._sanitize_openai_compatible_kwargs(kwargs)
    kwargs = client._strip_unsupported_params(kwargs)
    kwargs['stream'] = True
    kwargs.pop('model', None)
    kwargs.setdefault('stream_options', {'include_usage': True})
    try:
        stream = await client.async_client.chat.completions.create(
            model=client.model_name,
            messages=messages,  # type: ignore[arg-type]
            **kwargs,
        )
    except Exception as e:
        raise client._map_openai_error(e) from e
    try:
        async for chunk in stream:  # type: ignore[attr-defined]
            yield chunk.model_dump()
    except Exception as e:
        raise client._map_openai_error(e) from e
