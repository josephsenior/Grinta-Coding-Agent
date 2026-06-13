"""OpenCode Zen OpenAI Responses API transport."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any


def _message_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get('type') == 'text' and isinstance(item.get('text'), str):
                    parts.append(item['text'])
                elif isinstance(item.get('text'), str):
                    parts.append(item['text'])
        return '\n'.join(parts)
    return str(content or '')


def _messages_to_responses_input(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert chat messages to Responses API input items."""
    input_items: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get('role') or 'user').strip().lower()
        if role == 'tool':
            call_id = message.get('tool_call_id') or message.get('id')
            if call_id:
                input_items.append(
                    {
                        'type': 'function_call_output',
                        'call_id': str(call_id),
                        'output': _message_content_to_text(message.get('content')),
                    }
                )
            continue
        if role not in {'user', 'assistant', 'system', 'developer'}:
            role = 'user'
        content = _message_content_to_text(message.get('content'))
        item: dict[str, Any] = {'role': role, 'content': content}
        input_items.append(item)
    return input_items


def _extract_responses_tool_calls(response: Any) -> list[dict[str, Any]] | None:
    tool_calls: list[dict[str, Any]] = []
    for item in getattr(response, 'output', None) or []:
        item_type = getattr(item, 'type', None)
        if item_type != 'function_call':
            continue
        name = getattr(item, 'name', None)
        call_id = getattr(item, 'call_id', None) or getattr(item, 'id', None)
        arguments = getattr(item, 'arguments', None) or '{}'
        if not name or not call_id:
            continue
        tool_calls.append(
            {
                'id': str(call_id),
                'type': 'function',
                'function': {
                    'name': str(name),
                    'arguments': str(arguments),
                },
            }
        )
    return tool_calls or None


def _extract_responses_text(response: Any) -> str:
    output_text = getattr(response, 'output_text', None)
    if isinstance(output_text, str) and output_text.strip():
        return output_text
    chunks: list[str] = []
    for item in getattr(response, 'output', None) or []:
        if getattr(item, 'type', None) != 'message':
            continue
        for part in getattr(item, 'content', None) or []:
            text = getattr(part, 'text', None)
            if isinstance(text, str) and text:
                chunks.append(text)
    return '\n'.join(chunks)


def _build_responses_kwargs(client: Any, messages: list[dict[str, Any]], kwargs: dict[str, Any]) -> dict[str, Any]:
    from backend.inference import direct_clients as dc

    payload = dict(kwargs)
    payload.pop('model', None)
    payload.pop('messages', None)
    payload.pop('stream', None)
    payload.pop('stream_options', None)
    payload['model'] = client.model_name
    payload['input'] = _messages_to_responses_input(messages)
    if 'max_tokens' in payload and 'max_output_tokens' not in payload:
        payload['max_output_tokens'] = payload.pop('max_tokens')
    if 'max_completion_tokens' in payload and 'max_output_tokens' not in payload:
        payload['max_output_tokens'] = payload.pop('max_completion_tokens')
    return dc._sanitize_openai_compatible_kwargs(payload)


def _responses_usage(response: Any) -> dict[str, int]:
    usage = getattr(response, 'usage', None)
    if usage is None:
        return {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}
    input_tokens = getattr(usage, 'input_tokens', None)
    output_tokens = getattr(usage, 'output_tokens', None)
    total_tokens = getattr(usage, 'total_tokens', None)
    if input_tokens is None and hasattr(usage, 'prompt_tokens'):
        input_tokens = usage.prompt_tokens
    if output_tokens is None and hasattr(usage, 'completion_tokens'):
        output_tokens = usage.completion_tokens
    prompt = int(input_tokens or 0)
    completion = int(output_tokens or 0)
    total = int(total_tokens if total_tokens is not None else prompt + completion)
    return {
        'prompt_tokens': prompt,
        'completion_tokens': completion,
        'total_tokens': total,
    }


def _to_llm_response(client: Any, response: Any) -> Any:
    from backend.inference import direct_clients as dc

    return dc.LLMResponse(
        content=_extract_responses_text(response),
        model=getattr(response, 'model', client.model_name),
        usage=_responses_usage(response),
        id=getattr(response, 'id', '') or '',
        finish_reason=getattr(response, 'status', '') or '',
        tool_calls=_extract_responses_tool_calls(response),
    )


def _prepare_opencode_responses_messages(
    client: Any,
    messages: list[dict[str, Any]],
    kwargs: dict[str, Any],
) -> list[dict[str, Any]]:
    from backend.inference.mappers.openai import strip_prompt_cache_hints_from_messages

    return strip_prompt_cache_hints_from_messages(
        messages,
        model=kwargs.get('model', client.model_name),
        provider=getattr(client, '_provider_name', None),
    )


def completion(client: Any, messages: list[dict[str, Any]], **kwargs) -> Any:
    from backend.inference import direct_clients as dc

    messages = _prepare_opencode_responses_messages(client, messages, kwargs)
    messages = client._clean_messages(messages)
    request_kwargs = _build_responses_kwargs(client, messages, kwargs)
    request_kwargs = client._strip_unsupported_params(request_kwargs)
    request_kwargs = dc._with_default_timeout(request_kwargs, client._request_timeout)
    try:
        response = client.client.responses.create(**request_kwargs)
    except Exception as exc:
        raise client._map_openai_error(exc) from exc
    return _to_llm_response(client, response)


async def acompletion(client: Any, messages: list[dict[str, Any]], **kwargs) -> Any:
    from backend.inference import direct_clients as dc

    messages = _prepare_opencode_responses_messages(client, messages, kwargs)
    messages = client._clean_messages(messages)
    request_kwargs = _build_responses_kwargs(client, messages, kwargs)
    request_kwargs = client._strip_unsupported_params(request_kwargs)
    request_kwargs = dc._with_default_timeout(request_kwargs, client._request_timeout)
    try:
        response = await client.async_client.responses.create(**request_kwargs)
    except Exception as exc:
        raise client._map_openai_error(exc) from exc
    return _to_llm_response(client, response)


async def astream(
    client: Any, messages: list[dict[str, Any]], **kwargs
) -> AsyncIterator[dict[str, Any]]:
    from backend.inference import direct_clients as dc

    messages = _prepare_opencode_responses_messages(client, messages, kwargs)
    messages = client._clean_messages(messages)
    request_kwargs = _build_responses_kwargs(client, messages, kwargs)
    request_kwargs = client._strip_unsupported_params(request_kwargs)
    request_kwargs = dc._with_default_timeout(
        request_kwargs,
        client._request_timeout,
        streaming=True,
    )
    request_kwargs['stream'] = True
    try:
        stream = await client.async_client.responses.create(**request_kwargs)
    except Exception as exc:
        raise client._map_openai_error(exc) from exc

    async for event in stream:
        event_type = getattr(event, 'type', None)
        if event_type == 'response.output_text.delta':
            delta = getattr(event, 'delta', None)
            if isinstance(delta, str) and delta:
                yield {'choices': [{'delta': {'content': delta}}]}
        elif event_type == 'response.completed':
            break
