"""Unified text truncation utilities for CLI output.

Consolidates the various truncation functions previously scattered across
confirmation.py, reasoning_display.py, and other modules.

Provides consistent behavior with clear policies:
- ``shorten_middle``: Keeps head + tail (good for commands, paths)
- ``shorten_path``: Keeps tail only (good for file paths)
- ``truncate_line``: Keeps head with word boundary (good for labels)
"""

from __future__ import annotations


def shorten_middle(text: str, max_len: int = 88, head_min: int = 20) -> str:
    """Keep long text readable by preserving the start and the tail.

    Used for shell commands, long URLs, or any text where both the
    beginning and end are meaningful.

    Args:
        text: The text to shorten.
        max_len: Maximum allowed length (including ellipsis).
        head_min: Minimum characters to keep at the start.

    Returns:
        Shortened text with middle replaced by ``…``.
    """
    if not text or len(text) <= max_len:
        return text
    head_len = max(head_min, max_len // 2 - 2)
    tail_len = max(head_min, max_len - head_len - 1)
    return f'{text[:head_len]}…{text[-tail_len:]}'


def shorten_path(path: str, max_len: int = 48) -> str:
    """Keep path readable; favour the leaf folder + filename.

    Used for file paths where the most relevant information is at
    the end (filename and immediate parent).

    Args:
        path: The path to shorten.
        max_len: Maximum allowed length (including ellipsis).

    Returns:
        Shortened path with prefix replaced by ``…``.
    """
    if not path or len(path) <= max_len:
        return path
    tail = path[-(max_len - 1):]
    return '…' + tail


def truncate_line(label: str, max_len: int = 60) -> str:
    """Ellipsis at end of label, preferring a word boundary when there is room.

    Used for action labels, tool names, or any display text where
    breaking at a word boundary is preferred.

    Args:
        label: The text to truncate.
        max_len: Maximum allowed length (including ellipsis).

    Returns:
        Truncated text ending with ``…`` at a word boundary when possible.
    """
    text = (label or '').strip()
    if max_len <= 0 or len(text) <= max_len:
        return text
    if max_len <= 1:
        return '…'
    limit = max_len - 1
    chunk = text[:limit]
    if ' ' in chunk:
        at = chunk.rfind(' ')
        if at > max(6, limit // 4):
            chunk = chunk[:at].rstrip()
    return f'{chunk}…'


__all__ = [
    'shorten_middle',
    'shorten_path',
    'truncate_line',
]
