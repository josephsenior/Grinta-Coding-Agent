"""OpenAI-specific LLM data adapters and mappers."""

import copy
from typing import Any


def _extract_new_style_tool_calls(
    raw: list,
) -> list[dict[str, Any]] | None:
    result: list[dict[str, Any]] = []
    for tc in raw:
        entry: dict[str, Any] = {
            'id': getattr(tc, 'id', None) or 'call_0',
            'type': getattr(tc, 'type', None) or 'function',
            'function': {
                'name': getattr(getattr(tc, 'function', None), 'name', ''),
                'arguments': getattr(
                    getattr(tc, 'function', None), 'arguments', '{}'
                ),
            },
        }
        result.append(entry)
    return result or None


def _extract_legacy_function_call(fc: Any) -> list[dict[str, Any]] | None:
    if fc is None:
        return None
    name: Any = ''
    arguments: Any = '{}'
    if isinstance(fc, dict):
        name = fc.get('name', '')
        arguments = fc.get('arguments', '{}')
    else:
        name = getattr(fc, 'name', '')
        arguments = getattr(fc, 'arguments', '{}')
    if not (isinstance(name, str) and name.strip()):
        return None
    arguments_str = arguments if isinstance(arguments, str) else str(arguments)
    return [
        {
            'id': 'call_0',
            'type': 'function',
            'function': {
                'name': name,
                'arguments': arguments_str or '{}',
            },
        }
    ]


def extract_tool_calls(message: Any) -> list[dict[str, Any]] | None:
    """Extract tool_calls from an OpenAI ChatCompletionMessage."""
    raw = getattr(message, 'tool_calls', None)
    if raw:
        return _extract_new_style_tool_calls(raw)
    return _extract_legacy_function_call(getattr(message, 'function_call', None))


def _strip_cache_control_recursive(obj: Any) -> None:
    if isinstance(obj, dict):
        obj.pop('cache_control', None)
        for v in obj.values():
            _strip_cache_control_recursive(v)
    elif isinstance(obj, list):
        for item in obj:
            _strip_cache_control_recursive(item)


def strip_prompt_cache_hints_from_messages(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Remove Anthropic-style cache markers; OpenAI-compatible APIs do not accept them."""
    cleaned = copy.deepcopy(messages)
    for m in cleaned:
        _strip_cache_control_recursive(m)
    return cleaned
