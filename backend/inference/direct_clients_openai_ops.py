"""OpenAI-compatible provider operations for DirectLLMClient wrappers."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import Any


def _ensure_opencode_chat_completions_model_supported(client: Any) -> None:
    """Fail fast for OpenCode models that are not served via /chat/completions."""
    provider_name = getattr(client, '_provider_name', 'openai')
    if provider_name not in {'opencode', 'opencode-go'}:
        return

    from backend.inference.exceptions import BadRequestError
    from backend.inference.provider_resolver import (
        opencode_go_required_endpoint,
        opencode_required_endpoint,
    )

    if provider_name == 'opencode-go':
        required_endpoint = opencode_go_required_endpoint(client.model_name)
    else:
        required_endpoint = opencode_required_endpoint(client.model_name)
    if required_endpoint == '/chat/completions':
        return

    llm_provider = 'opencode-go' if provider_name == 'opencode-go' else 'opencode'
    example_models = (
        "'opencode-go/deepseek-v4-flash', 'opencode-go/glm-5.1', "
        "'opencode-go/kimi-k2.6'"
        if provider_name == 'opencode-go'
        else "'opencode/deepseek-v4-flash-free', 'opencode/minimax-m2.5', "
        "'opencode/kimi-k2.6'"
    )
    raise BadRequestError(
        (
            f'OpenCode model {client.model_name!r} is served via '
            f"'{required_endpoint}', but this Grinta transport uses "
            "'/chat/completions'. Select an OpenCode model served on "
            f"'/chat/completions' (for example: {example_models}), or switch "
            'provider/model route for non-chat families.'
        ),
        llm_provider=llm_provider,
        model=client.model_name,
    )


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


def _extract_oai_error_message(raw: str) -> str | None:
    """Try to extract a clean error message from an OpenAI error body.

    Handles both real JSON and Python-repr dicts (single quotes,
    ``datetime`` objects, etc.).
    """
    import ast
    import re

    m = re.search(r'\{.*\}', raw, re.DOTALL)
    if not m:
        return None  # type: ignore[unreachable]
    body_str = m.group(0)
    body: dict | None = None
    # Try JSON first (spec-compliant providers)
    try:
        import json as _json

        body = _json.loads(body_str)
    except Exception:
        pass
    # Fall back to Python-literal eval (OpenAI SDK uses str() on dicts)
    if body is None:
        try:
            body = ast.literal_eval(body_str)
        except Exception:
            return None
    if not isinstance(body, dict):
        return None
    error = body.get('error')
    if isinstance(error, dict):
        return error.get('message') or None
    if isinstance(error, str):
        return error
    return None


def simplify_openai_unauthorized_message(exc: Exception, status_code: int) -> str:
    """User-facing text for 401/403; drops misleading JSON-decode noise."""
    try:
        raw = str(exc)
    except Exception:
        raw = f'{type(exc).__name__} (unprintable exception)'
    if status_code == 403:
        reason = _extract_oai_error_message(raw) or 'access denied'
        if reason and reason[0].islower():
            reason = reason[0].upper() + reason[1:]
        if not reason.endswith('.'):
            reason += '.'
        return reason
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


def _is_deepseek_thinking_replay_model(client: Any) -> bool:
    provider_name = str(getattr(client, '_provider_name', '') or '').lower()
    model_name = str(getattr(client, 'model_name', '') or '').lower()
    if provider_name not in {'deepseek', 'opencode', 'opencode-go'}:
        return False
    return (
        model_name.startswith('deepseek-v4')
        or model_name.startswith('deepseek-reasoner')
        or model_name.startswith('deepseek-r1')
    )


def _message_content_to_text(content: Any) -> str:
    if content is None:
        return ''
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        text = content.get('text')
        return text if isinstance(text, str) else str(content)
    if isinstance(content, list):
        return ''.join(_message_content_to_text(item) for item in content)
    return str(content)


def _flatten_stale_deepseek_assistant_message(msg: dict[str, Any]) -> dict[str, Any]:
    from backend.cli.tool_call_display import flatten_tool_call_for_history

    text = _message_content_to_text(msg.get('content')).strip()
    tool_lines: list[str] = []
    for tool_call in msg.get('tool_calls') or []:
        if not isinstance(tool_call, dict):
            continue
        function = tool_call.get('function') or {}
        name = str(function.get('name') or 'tool')
        arguments = str(function.get('arguments') or '{}')
        tool_lines.append(flatten_tool_call_for_history(name, arguments))

    content = '\n'.join(part for part in [text, *tool_lines] if part).strip()
    return {
        'role': 'user',
        'content': content
        or '[Previous assistant response omitted missing reasoning trace.]',
    }


def _flatten_stale_deepseek_tool_message(msg: dict[str, Any]) -> dict[str, Any]:
    name = str(msg.get('name') or 'tool')
    content = _message_content_to_text(msg.get('content')).strip()
    return {
        'role': 'user',
        'content': f'[Tool result from {name}]\n{content}'.strip(),
    }


def _recover_deepseek_thinking_history(
    client: Any,
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Recover sessions created before reasoning_content replay was preserved."""
    if not _is_deepseek_thinking_replay_model(client):
        return messages

    has_stale_assistant = any(
        isinstance(msg, dict)
        and msg.get('role') == 'assistant'
        and not msg.get('reasoning_content')
        for msg in messages
    )
    if not has_stale_assistant:
        return messages

    recovered: list[dict[str, Any]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            recovered.append(msg)  # type: ignore[unreachable]
            continue  # type: ignore[unreachable]
        role = msg.get('role')
        if role == 'assistant' and not msg.get('reasoning_content'):
            recovered.append(_flatten_stale_deepseek_assistant_message(msg))
            continue
        if role == 'tool':
            recovered.append(_flatten_stale_deepseek_tool_message(msg))
            continue
        recovered.append(msg)
    return recovered


def completion(client: Any, messages: list[dict[str, Any]], **kwargs) -> Any:
    from backend.inference import direct_clients as dc
    from backend.inference.mappers.openai import strip_prompt_cache_hints_from_messages

    _ensure_opencode_chat_completions_model_supported(client)
    messages = strip_prompt_cache_hints_from_messages(messages)
    messages = _recover_deepseek_thinking_history(client, messages)
    messages = client._clean_messages(messages)
    kwargs = dc._sanitize_openai_compatible_kwargs(kwargs)
    kwargs = client._strip_unsupported_params(kwargs)
    kwargs['model'] = client.model_name

    response = _call_openai_chat(client, messages, kwargs)
    _warn_empty_response(response, client.model_name)
    return _build_llm_response(response, client)


def _call_openai_chat(client, messages, kwargs):
    try:
        return client.client.chat.completions.create(messages=messages, **kwargs)
    except Exception as e:
        raise client._map_openai_error(e) from e


def _warn_empty_response(response, model_name):
    from backend.inference import direct_clients as dc

    if not getattr(response, 'choices', None) or len(response.choices) == 0:
        from backend.inference.exceptions import BadRequestError

        raise BadRequestError(
            'OpenAI completion returned no choices',
            llm_provider='openai',
            model=model_name,
        )
    first = response.choices[0]
    msg = first.message
    content_value = getattr(msg, 'content', None)
    if content_value is None or (
        isinstance(content_value, str) and not content_value.strip()
    ):
        try:
            msg_dump = msg.model_dump() if hasattr(msg, 'model_dump') else str(msg)
        except Exception:
            msg_dump = str(msg)
        dc.logger.warning(
            'OpenAI-compatible completion returned empty message (no tool calls). '
            'model=%s finish_reason=%s msg=%s',
            model_name,
            getattr(first, 'finish_reason', None),
            msg_dump,
        )


def _build_llm_response(response, client):
    from backend.inference import direct_clients as dc

    first = response.choices[0]
    msg = first.message
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
        tool_calls=client._extract_openai_tool_calls(msg),
    )


async def acompletion(client: Any, messages: list[dict[str, Any]], **kwargs) -> Any:
    from backend.inference import direct_clients as dc
    from backend.inference.exceptions import BadRequestError
    from backend.inference.mappers.openai import strip_prompt_cache_hints_from_messages

    _ensure_opencode_chat_completions_model_supported(client)
    messages = strip_prompt_cache_hints_from_messages(messages)
    messages = _recover_deepseek_thinking_history(client, messages)
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

    _ensure_opencode_chat_completions_model_supported(client)
    messages = strip_prompt_cache_hints_from_messages(messages)
    messages = _recover_deepseek_thinking_history(client, messages)
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
