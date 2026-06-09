"""Marker stripping / redaction helpers for assistant text and history."""

from __future__ import annotations

import json
import re
from typing import Any

from backend.cli._tool_display.constants import (
    _INTERNAL_RESULT_MARKER_RE,
    _PROTOCOL_ECHO_PREFIXES,
    _TASK_JSON_OBJ_RE,
    _TOOL_CALL_PREFIX,
    _TOOL_CALL_PREFIX_PARTIAL,
)


def strip_tool_call_marker_lines(text: str) -> str:
    """Drop whole lines that are only a friendly ``[Tool call] …`` summary."""
    if _TOOL_CALL_PREFIX_PARTIAL not in text:
        return text
    kept: list[str] = []
    for line in text.splitlines(keepends=True):
        rest = line.lstrip()
        if not rest.startswith(_TOOL_CALL_PREFIX_PARTIAL):
            kept.append(line)
            continue
        # Partial fragment (no closing ``]``) — always drop during streaming.
        if not rest.startswith(_TOOL_CALL_PREFIX):
            continue
        after = rest[len(_TOOL_CALL_PREFIX) :].lstrip()
        if re.match(r'^[A-Za-z0-9_]+\s*\(', after):
            kept.append(line)
            continue
    return ''.join(kept)


def _line_starts_protocol_prefix(line: str) -> bool:
    stripped = line.lstrip()
    return any(stripped.startswith(prefix) for prefix in _PROTOCOL_ECHO_PREFIXES)


def strip_protocol_echo_blocks(text: str) -> str:
    """Drop echoed tool-result / command-observation protocol blocks."""
    if not text or '[' not in text:
        return text

    parts = re.split(r'(\n\s*\n)', text)
    kept_parts: list[str] = []
    for part in parts:
        stripped = part.strip()
        if not stripped:
            kept_parts.append(part)
            continue
        if any(stripped.startswith(prefix) for prefix in _PROTOCOL_ECHO_PREFIXES):
            continue
        kept_parts.append(part)

    text = ''.join(kept_parts)
    return ''.join(
        line
        for line in text.splitlines(keepends=True)
        if not _line_starts_protocol_prefix(line)
    )


_BRACKET_TOOL_SENTINELS = frozenset(
    {
        '[TOOL_CALL]',
        '[TOOL_CALLS]',
        '[START_TOOL_CALL]',
        '[START_TOOL_CALLS]',
        '[BEGIN_TOOL_CALL]',
        '[BEGIN_TOOL_CALLS]',
        '[END_TOOL_CALL]',
        '[END_TOOL_CALLS]',
        '[/TOOL_CALL]',
        '[/TOOL_CALLS]',
    }
)

_MINIMAX_SPLIT_TOOL_TAG_RE = re.compile(
    r'\]<?\]minimax\[>\[?<\s*(/?)\s*tool_call\b',
    re.IGNORECASE,
)

_INVOKE_BLOCK_RE = re.compile(
    r'<\s*invoke\s+name\s*=\s*["\']?([A-Za-z_][A-Za-z0-9_-]*)["\']?\s*>'
    r'(.*?)(?:</\s*invoke\s*>|\Z)',
    re.DOTALL | re.IGNORECASE,
)

_INVOKE_PARAMETER_RE = re.compile(
    r'<\s*parameter(?:(?:\s*=\s*|\s+name\s*=\s*["\']?)'
    r'([A-Za-z_][A-Za-z0-9_-]*)["\']?)?\s*>'
    r'(.*?)</\s*parameter\s*>',
    re.DOTALL | re.IGNORECASE,
)

_TOOL_TRANSPORT_MARKUP_RE = re.compile(
    r'^\s*\[/?(?:tool_calls?|start_tool_calls?|begin_tool_calls?|end_tool_calls?)\]\s*$'
    r'|^\s*\[EDIT_DIFF\]\b'
    r'|\[Tool call\]'
    r'|<\s*/?\s*(?:minimax:)?tool_call\b'
    r'|<\s*invoke\s+name\s*='
    r'|<\s*function(?:\s*=|\s+name\s*=)',
    re.MULTILINE | re.IGNORECASE,
)


def _normalize_minimax_split_tool_markup(text: str) -> str:
    """Normalize MiniMax split-stream wrappers into ordinary XML-like tags."""
    if 'minimax' not in text.lower():
        return text

    def repl(match: re.Match[str]) -> str:
        slash = '/' if match.group(1) else ''
        return f'<{slash}minimax:tool_call'

    return _MINIMAX_SPLIT_TOOL_TAG_RE.sub(repl, text)


def contains_tool_transport_markup(text: str) -> bool:
    """Return True when text contains raw model/tool transport markup."""
    if not text:
        return False
    normalized = _normalize_minimax_split_tool_markup(text)
    return bool(_TOOL_TRANSPORT_MARKUP_RE.search(normalized))


def strip_bracket_tool_transport_blocks(text: str) -> str:
    """Drop raw bracket-based tool transport from user-visible text."""
    if not text or ('[' not in text and '<' not in text):
        return text

    kept: list[str] = []
    dropping_edit_diff = False
    for line in text.splitlines(keepends=True):
        compact = line.strip()
        upper = compact.upper()
        if upper in _BRACKET_TOOL_SENTINELS:
            continue
        if upper.startswith('[EDIT_DIFF]'):
            dropping_edit_diff = True
            continue
        if dropping_edit_diff:
            if compact:
                continue
            dropping_edit_diff = False
            continue
        if upper in {
            '<THINK>',
            '</THINK>',
            '<REDACTED_THINKING>',
            '</REDACTED_THINKING>',
        }:
            continue
        kept.append(line)
    return ''.join(kept)


def _balanced_json_object_end(s: str, open_curly: int) -> int | None:
    """Return index after the ``}`` that closes the object starting at *open_curly*."""
    depth = 0
    in_str = False
    esc = False
    for pos in range(open_curly, len(s)):
        ch = s[pos]
        if in_str:
            if esc:
                esc = False
            elif ch == '\\':
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return pos + 1
    return None


def _scan_tool_call_marker(text: str, marker_idx: int) -> tuple[int, int] | None:
    """Locate the span of a ``[Tool call] name({...})`` marker.

    Returns ``(start, end)`` of the full marker (including a trailing newline)
    or ``None`` when the marker is not yet complete.  The caller decides whether
    to truncate the output stream (in-progress marker) or emit the prose
    surrounding it.
    """
    rest_start = marker_idx + len(_TOOL_CALL_PREFIX)
    json_start = _locate_tool_call_json_start(text, rest_start)
    if json_start is None:
        return None
    end_json = _balanced_json_object_end(text, json_start)
    if end_json is None:
        return None
    end = _scan_tool_call_close(text, end_json)
    if end is None:
        return None
    return marker_idx, end


def _locate_tool_call_json_start(text: str, rest_start: int) -> int | None:
    n = len(text)
    rest = text[rest_start:]
    lstripped = rest.lstrip()
    ws = len(rest) - len(lstripped)
    if not re.match(r'^([A-Za-z0-9_]+)\(', lstripped):
        return None  # type: ignore[unreachable]
    open_paren_in_rest = lstripped.find('(')
    args_begin = rest_start + ws + open_paren_in_rest + 1
    tail = text[args_begin:].lstrip()
    json_shift = len(text[args_begin:]) - len(tail)
    json_start = args_begin + json_shift
    if json_start >= n or text[json_start] != '{':
        return None
    return json_start


def _scan_tool_call_close(text: str, end_json: int) -> int | None:
    n = len(text)
    k = end_json
    while k < n and text[k] in ' \t\r':
        k += 1
    if k >= n or text[k] != ')':
        return None
    end = k + 1
    if end < n and text[end] == '\n':
        end += 1
    return end


def redact_streamed_tool_call_markers(text: str) -> str:
    """Remove ``[Tool call] name({...})`` spans from assistant-visible text."""
    text = _normalize_minimax_split_tool_markup(text)
    text = strip_bracket_tool_transport_blocks(
        strip_protocol_echo_blocks(strip_tool_call_marker_lines(text))
    )
    text = _redact_xml_tool_call_blocks(text)
    if _TOOL_CALL_PREFIX not in text:
        return text
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        j = text.find(_TOOL_CALL_PREFIX, i)
        if j < 0:
            out.append(text[i:])
            break
        out.append(text[i:j])
        rest_start = j + len(_TOOL_CALL_PREFIX)
        rest = text[rest_start:]
        lstripped = rest.lstrip()
        m = re.match(r'^([A-Za-z0-9_]+)\(', lstripped)
        if not m:
            out.append(text[j:rest_start])  # type: ignore[unreachable]
            i = rest_start
            continue
        span = _scan_tool_call_marker(text, j)
        if span is None:
            # JSON not yet complete — drop everything from the prefix onwards
            # to avoid leaking a stray '[' into the draft-reply live preview.
            return ''.join(out).rstrip()
        _start, end = span
        i = end
    return ''.join(out)


def extract_tool_calls_from_text_markers(text: str) -> list[dict[str, Any]]:
    """Extract structured tool-call dicts from text-encoded tool-call spans."""
    text = _normalize_minimax_split_tool_markup(text)
    results = _extract_xml_tool_call_blocks(text)
    call_index = len(results)

    if _TOOL_CALL_PREFIX not in text:
        return results

    i = 0
    n = len(text)

    while i < n:
        j = text.find(_TOOL_CALL_PREFIX, i)
        if j < 0:
            break
        rest_start = j + len(_TOOL_CALL_PREFIX)
        rest = text[rest_start:]
        lstripped = rest.lstrip()
        m = re.match(r'^([A-Za-z0-9_]+)\(', lstripped)
        if not m:
            i = rest_start  # type: ignore[unreachable]
            continue
        fn_name = m.group(1)
        span = _scan_tool_call_marker(text, j)
        if span is None:
            i = rest_start
            continue
        _start, end = span
        # Recover the JSON arguments substring inside the marker.
        ws = len(rest) - len(lstripped)
        open_paren_in_rest = lstripped.find('(')
        args_begin = rest_start + ws + open_paren_in_rest + 1
        tail = text[args_begin:].lstrip()
        json_shift = len(text[args_begin:]) - len(tail)
        json_start = args_begin + json_shift
        end_json = _balanced_json_object_end(text, json_start)
        if end_json is None:
            i = end
            continue
        arguments_str = text[json_start:end_json]
        results.append(
            {
                'id': f'call_{call_index + 1:02d}',
                'type': 'function',
                'function': {'name': fn_name, 'arguments': arguments_str},
            }
        )
        call_index += 1
        i = end

    return results


def _redact_xml_tool_call_blocks(text: str) -> str:
    if '<' not in text or 'tool_call' not in text:
        return text
    out: list[str] = []
    pos = 0
    while pos < len(text):
        block = _find_next_xml_tool_call_block(text, pos)
        if block is None:
            out.append(text[pos:])
            break
        start, end, _tag, _attrs, _body = block
        out.append(text[pos:start])
        pos = end
    return ''.join(out).rstrip()


def _extract_xml_tool_call_blocks(text: str) -> list[dict[str, Any]]:
    if '<' not in text or 'tool_call' not in text:
        return []
    results: list[dict[str, Any]] = []
    pos = 0
    while pos < len(text):
        block = _find_next_xml_tool_call_block(text, pos)
        if block is None:
            break
        _start, end, _tag, attrs, body = block
        parsed = _xml_tool_call_to_dict(attrs, body, len(results))
        if parsed is not None:
            results.append(parsed)
        pos = end
    return results


def _find_next_xml_tool_call_block(
    text: str,
    pos: int,
) -> tuple[int, int, str, dict[str, str], str] | None:
    lower = text.lower()
    candidates = [
        idx
        for idx in (
            lower.find('<minimax:tool_call', pos),
            lower.find('<tool_call', pos),
        )
        if idx >= 0
    ]
    if not candidates:
        return None
    start = min(candidates)
    tag_end = text.find('>', start)
    if tag_end < 0:
        return start, len(text), '', {}, text[start:]

    start_tag = text[start + 1 : tag_end].strip()
    tag_name = start_tag.split(None, 1)[0].strip().lower()
    attrs_text = start_tag[len(tag_name) :].strip()
    close = f'</{tag_name}>'
    close_start = lower.find(close, tag_end + 1)
    if close_start < 0:
        return (
            start,
            len(text),
            tag_name,
            _parse_tag_attrs(attrs_text),
            text[tag_end + 1 :],
        )
    end = close_start + len(close)
    return (
        start,
        end,
        tag_name,
        _parse_tag_attrs(attrs_text),
        text[tag_end + 1 : close_start],
    )


_TAG_ATTR_RE = re.compile(
    r'([a-zA-Z_][\w:.-]*)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s>]+))'
)


def _parse_tag_attrs(attrs_text: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for match in _TAG_ATTR_RE.finditer(attrs_text):
        key = match.group(1).strip().lower()
        value = match.group(2) if match.group(2) is not None else (
            match.group(3) if match.group(3) is not None else match.group(4) or ''
        )
        if key:
            attrs[key] = value
    return attrs


def _extract_name_from_payload(payload: dict[str, Any]) -> str | None:
    return (
        payload.get('name')
        or payload.get('tool')
        or payload.get('function_name')
    )


def _extract_arguments_from_payload(
    payload: dict[str, Any], name: str | None
) -> Any:
    function_payload = payload.get('function')
    if isinstance(function_payload, dict):
        arguments = function_payload.get('arguments')
        if arguments is not None:
            return arguments

    arguments = payload.get('arguments') or payload.get('input')
    if arguments is not None:
        return arguments

    if name:
        return {
            k: v
            for k, v in payload.items()
            if k not in {'name', 'tool', 'function_name', 'function'}
        }
    return None


def _parse_json_body(body_text: str) -> tuple[str | None, Any]:
    try:
        payload = json.loads(body_text)
    except json.JSONDecodeError:
        return None, None

    if not isinstance(payload, dict):
        return None, None

    name = _extract_name_from_payload(payload)
    function_payload = payload.get('function')
    if isinstance(function_payload, dict):
        name = name or function_payload.get('name')

    arguments = _extract_arguments_from_payload(payload, name)
    return name, arguments


def _xml_tool_call_to_dict(
    attrs: dict[str, str],
    body: str,
    index: int,
) -> dict[str, Any] | None:
    body_text = (body or '').strip()
    name = attrs.get('name') or attrs.get('tool') or attrs.get('function')
    arguments: Any = None

    if body_text.startswith('{'):
        json_name, json_args = _parse_json_body(body_text)
        if json_name:
            name = name or json_name
        if json_args is not None:
            arguments = json_args

    if not name:
        invoke = _parse_invoke_body(body_text)
        if invoke is not None:
            name, arguments = invoke

    if not name:
        return None

    if arguments is None:
        arguments = {'command': body_text} if body_text else {}

    if isinstance(arguments, str):
        arguments_str = arguments
    else:
        arguments_str = json.dumps(arguments, ensure_ascii=False, separators=(',', ':'))

    return {
        'id': f'call_xml_{index + 1:02d}',
        'type': 'function',
        'function': {'name': str(name), 'arguments': arguments_str},
    }


def _parse_invoke_body(body_text: str) -> tuple[str, Any] | None:
    invoke_m = _INVOKE_BLOCK_RE.search(body_text)
    if invoke_m is None:
        return None
    name = invoke_m.group(1)
    invoke_body = (invoke_m.group(2) or '').strip()
    if not invoke_body:
        return name, {}
    if invoke_body.startswith('{'):
        try:
            payload = json.loads(invoke_body)
        except json.JSONDecodeError:
            return None
        if isinstance(payload, dict):
            return name, payload
        return None

    params = {
        str(match.group(1)): _trim_parameter_body(match.group(2))
        for match in _INVOKE_PARAMETER_RE.finditer(invoke_body)
        if match.group(1)
    }
    if params:
        return name, params
    return None


def _trim_parameter_body(value: str) -> str:
    if value.startswith('\n'):
        value = value[1:]
    if value.endswith('\n'):
        value = value[:-1]
    return value


def redact_internal_result_markers(text: str) -> str:
    """Strip internal ``[TAG] {json}`` or ``[TAG] text`` markers from user-visible text."""
    if '[' in text:
        text = _INTERNAL_RESULT_MARKER_RE.sub('', text)

    text = re.sub(
        r'\n?<APP_RESULT_VALIDATION>.*?(?:</APP_RESULT_VALIDATION>|$)',
        '',
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    cleaned = re.sub(r'\n{3,}', '\n\n', text)
    return cleaned.strip()


def redact_task_list_json_blobs(text: str) -> str:
    """Strip task-object JSON blobs from streaming text."""
    cleaned = _TASK_JSON_OBJ_RE.sub('', text)
    cleaned = re.sub(r'[\s,]+\]', ']', cleaned)
    cleaned = re.sub(r'\[\s*\]', '', cleaned)
    return cleaned.strip()
