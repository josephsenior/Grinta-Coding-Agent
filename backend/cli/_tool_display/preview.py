"""History flattening, MCP previews, and tool-JSON parsing helpers."""

from __future__ import annotations

import json
from typing import Any

from backend.cli._tool_display.constants import _TOOL_CALL_PREFIX
from backend.cli._tool_display.summarize import (
    _preview_result_item,
    _summarize_raw_mcp_text,
    _summarize_result_collection,
    _trunc,
    format_tool_invocation_line,
    parse_tool_arguments_json,
)


def flatten_tool_call_for_history(name: str, arguments: str) -> str:
    """Single line for cross-family assistant history (no raw JSON)."""
    parsed = parse_tool_arguments_json(arguments)
    if parsed is not None:
        icon, label = format_tool_invocation_line(name, parsed)
        return f'{_TOOL_CALL_PREFIX} {icon} {label}'
    return f'{_TOOL_CALL_PREFIX} {name}'


def looks_like_streaming_tool_arguments(text: str) -> bool:
    """True when *text* looks like JSON tool arguments but chunk is not flagged."""
    s = text.lstrip()
    if not s.startswith('{'):
        return False
    markers = (
        '"command"',
        '"path"',
        '"tool_name"',
        '"arguments"',
        '"text_editor"',
        '"function"',
    )
    return any(m in text for m in markers)


# ---------------------------------------------------------------------------
# MCP preview
# ---------------------------------------------------------------------------


def _mcp_count_summary(data: dict[str, Any]) -> str | None:
    for count_key in ('total_count', 'count', 'matches', 'total'):
        v = data.get(count_key)
        if isinstance(v, int):
            label = data.get('query') or data.get('pattern') or ''
            return f'{v} matches' + (f' for "{_trunc(label, 40)}"' if label else '')
    return None


def _mcp_search_code_summary(data: dict[str, Any], content: str) -> str | None:
    if 'search_code' in content or data.get('tool_name') == 'search_code':
        results = data.get('results')
        count = (
            len(results)
            if isinstance(results, list)
            else data.get('total_count', 0)
        )
        return f'{count} matches found'
    return None


def _mcp_collection_summary(data: dict[str, Any], *, max_len: int) -> str | None:
    for list_key in ('results', 'items', 'entries', 'documents', 'matches'):
        value = data.get(list_key)
        if isinstance(value, list):
            return _summarize_result_collection(value, label=list_key, max_len=max_len)
    return None


def _mcp_text_field_summary(data: dict[str, Any], *, max_len: int) -> str | None:
    for key in ('text', 'message', 'content', 'summary', 'result', 'output'):
        v = data.get(key)
        if isinstance(v, str) and v.strip():
            return _summarize_raw_mcp_text(v, max_len=max_len)
        if isinstance(v, list) and v:
            return _summarize_result_collection(v, max_len=max_len)
        if isinstance(v, dict) and v:
            try:
                nested = json.dumps(v, ensure_ascii=False)
            except (TypeError, ValueError):
                nested = str(v)
            return _trunc(nested, max_len)
    return None


def _mcp_error_summary(data: dict[str, Any], *, max_len: int) -> str | None:
    err = data.get('error') or data.get('detail')
    if isinstance(err, str) and err.strip():
        return _trunc(err, max_len)
    if isinstance(err, dict):
        msg = err.get('message') or err.get('msg')
        if isinstance(msg, str):
            return _trunc(msg, max_len)
    return None


def _mcp_dict_preview(data: dict[str, Any], *, content: str, max_len: int) -> str:
    for builder in (
        _mcp_count_summary,
        lambda d: _mcp_search_code_summary(d, content),
        lambda d: _mcp_collection_summary(d, max_len=max_len),
        lambda d: _mcp_text_field_summary(d, max_len=max_len),
        lambda d: _mcp_error_summary(d, max_len=max_len),
    ):
        result = builder(data)
        if result:
            return result
    try:
        return _trunc(json.dumps(data, ensure_ascii=False), max_len)
    except (TypeError, ValueError):
        return _summarize_raw_mcp_text(content, max_len=max_len)


def mcp_result_user_preview(content: str, *, max_len: int = 400) -> str:
    """Turn MCP JSON/text tool output into a short user-facing string."""
    s = (content or '').strip()
    if not s:
        return ''
    if not s.startswith('{') and not s.startswith('['):
        return _summarize_raw_mcp_text(s, max_len=max_len)

    try:
        data = json.loads(s)
    except (json.JSONDecodeError, TypeError, ValueError):
        return _summarize_raw_mcp_text(s, max_len=max_len)

    if isinstance(data, dict):
        return _mcp_dict_preview(data, content=content, max_len=max_len)
    if isinstance(data, list) and data:
        return _summarize_result_collection(data, max_len=max_len)
    try:
        return _trunc(json.dumps(data, ensure_ascii=False), max_len)
    except (TypeError, ValueError):
        return _summarize_raw_mcp_text(s, max_len=max_len)


# ---------------------------------------------------------------------------
# Try-format-message-as-tool-json
# ---------------------------------------------------------------------------


def _coerce_tool_args(arguments: Any) -> dict[str, Any]:
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, TypeError, ValueError):
            return {'raw': arguments[:200]}
    return {}


def _format_tool_call(
    name: str, arguments: Any, *, use_icons: bool, lines: list[str]
) -> str | None:
    args_dict = _coerce_tool_args(arguments)
    icon, label = format_tool_invocation_line(
        name, args_dict or None, use_icons=use_icons
    )
    lines.append(f'{icon} {label}' if icon else label)
    return name


def _walk_tool_calls_dict(
    data: dict[str, Any],
    *,
    use_icons: bool,
    lines: list[str],
) -> str | None:
    if isinstance(data.get('tool_calls'), list):
        first: str | None = None
        for tc in data['tool_calls']:
            if not isinstance(tc, dict):
                continue
            fn = tc.get('function')
            if isinstance(fn, dict):
                name = _format_tool_call(
                    str(fn.get('name', 'tool')),
                    fn.get('arguments', {}),
                    use_icons=use_icons,
                    lines=lines,
                )
                first = first or name
        return first
    if 'name' in data and 'arguments' in data:
        return _format_tool_call(
            str(data.get('name', 'tool')),
            data.get('arguments'),
            use_icons=use_icons,
            lines=lines,
        )
    if isinstance(data.get('function'), dict):
        fn = data['function']
        return _format_tool_call(
            str(fn.get('name', 'tool')),
            fn.get('arguments', {}),
            use_icons=use_icons,
            lines=lines,
        )
    return None


def _walk_tool_calls_list(
    data: list[Any],
    *,
    use_icons: bool,
    lines: list[str],
) -> str | None:
    first: str | None = None
    for item in data:
        if not isinstance(item, dict):
            continue
        fn = item.get('function')
        if isinstance(fn, dict):
            name = _format_tool_call(
                str(fn.get('name', 'tool')),
                fn.get('arguments', {}),
                use_icons=use_icons,
                lines=lines,
            )
            first = first or name
    return first


def try_format_message_as_tool_json(
    content: str, *, use_icons: bool = True
) -> tuple[str, str] | None:
    """If *content* is assistant tool JSON, return (icon, friendly multiline text)."""
    from backend.cli._tool_display.headline import tool_headline

    s = content.strip()
    if not s.startswith('{') and not s.startswith('['):
        return None
    try:
        data = json.loads(s)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None

    lines: list[str] = []
    first: str | None = None
    if isinstance(data, dict):
        first = _walk_tool_calls_dict(data, use_icons=use_icons, lines=lines)
        if first is None:
            return None
    elif isinstance(data, list):
        first = _walk_tool_calls_list(data, use_icons=use_icons, lines=lines)
    else:
        return None

    if not lines:
        return None
    icon0, _ = tool_headline(first or '', use_icons=use_icons)
    return icon0, '\n'.join(lines)


# Re-export internal preview helper used by other modules in this package.
__all__ = [
    'flatten_tool_call_for_history',
    'looks_like_streaming_tool_arguments',
    'mcp_result_user_preview',
    'try_format_message_as_tool_json',
    '_preview_result_item',
]
