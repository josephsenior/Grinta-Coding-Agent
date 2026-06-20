"""Provider-neutral tool-call flattening for cross-family message history."""

from __future__ import annotations

import json
from typing import Any

_TOOL_CALL_PREFIX = '[Tool call]'


def _compact_argument_summary(arguments: dict[str, Any], *, limit: int = 80) -> str:
    parts: list[str] = []
    for key, value in arguments.items():
        if len(parts) >= 3:
            parts.append('…')
            break
        if isinstance(value, str):
            text = value.replace('\n', ' ').strip()
            if len(text) > 40:
                text = text[:37] + '…'
            parts.append(f'{key}={text!r}')
        elif value is None:
            parts.append(f'{key}=null')
        else:
            parts.append(f'{key}={value!r}')
    summary = ', '.join(parts)
    if len(summary) > limit:
        return summary[: limit - 1] + '…'
    return summary


def flatten_tool_call_for_history(name: str, arguments: str) -> str:
    """Single line for cross-family assistant history (no raw JSON)."""
    parsed: Any
    try:
        parsed = json.loads(arguments or '{}')
    except (json.JSONDecodeError, TypeError):
        parsed = None
    if isinstance(parsed, dict) and parsed:
        summary = _compact_argument_summary(parsed)
        return f'{_TOOL_CALL_PREFIX} {name}({summary})'
    if arguments and arguments.strip() and arguments.strip() != '{}':
        compact = arguments.replace('\n', ' ').strip()
        if len(compact) > 80:
            compact = compact[:77] + '…'
        return f'{_TOOL_CALL_PREFIX} {name}({compact})'
    return f'{_TOOL_CALL_PREFIX} {name}'
