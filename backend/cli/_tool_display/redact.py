"""Marker stripping / redaction helpers for assistant text and history."""

from __future__ import annotations

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
        line for line in text.splitlines(keepends=True) if not _line_starts_protocol_prefix(line)
    )


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
        return None
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
    text = strip_protocol_echo_blocks(strip_tool_call_marker_lines(text))
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
            out.append(text[j:rest_start])
            i = rest_start
            continue
        span = _scan_tool_call_marker(text, j)
        if span is None:
            # JSON not yet complete — drop everything from the prefix onwards
            # to avoid leaking a stray '[' into the Draft Reply panel.
            return ''.join(out).rstrip()
        _start, end = span
        i = end
    return ''.join(out)


def extract_tool_calls_from_text_markers(text: str) -> list[dict[str, Any]]:
    """Extract structured tool-call dicts from ``[Tool call] name({...})`` spans."""
    if _TOOL_CALL_PREFIX not in text:
        return []

    results: list[dict[str, Any]] = []
    i = 0
    n = len(text)
    call_index = 0

    while i < n:
        j = text.find(_TOOL_CALL_PREFIX, i)
        if j < 0:
            break
        rest_start = j + len(_TOOL_CALL_PREFIX)
        rest = text[rest_start:]
        lstripped = rest.lstrip()
        m = re.match(r'^([A-Za-z0-9_]+)\(', lstripped)
        if not m:
            i = rest_start
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
    text = re.sub(r'\[TOOL_FALLBACK\].*?(?:\n|$)', '', text)
    cleaned = re.sub(r'\n{3,}', '\n\n', text)
    return cleaned.strip()


def redact_task_list_json_blobs(text: str) -> str:
    """Strip task-object JSON blobs from streaming text."""
    cleaned = _TASK_JSON_OBJ_RE.sub('', text)
    cleaned = re.sub(r'[\s,]+\]', ']', cleaned)
    cleaned = re.sub(r'\[\s*\]', '', cleaned)
    return cleaned.strip()
