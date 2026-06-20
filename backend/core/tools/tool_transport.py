"""Tool-transport markup detection (pure regex, no CLI deps)."""

from __future__ import annotations

import re

_MINIMAX_SPLIT_TOOL_TAG_RE = re.compile(
    r'\]<?\]minimax\[>\[?<\s*(/?)\s*tool_call\b',
    re.IGNORECASE,
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
