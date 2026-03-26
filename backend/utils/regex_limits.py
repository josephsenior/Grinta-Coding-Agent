"""Guardrails for user-supplied regular expressions (search, tools, etc.)."""

from __future__ import annotations

import re

# ReDoS and memory: cap pattern size for fallback search and similar paths.
MAX_USER_REGEX_PATTERN_CHARS = 4096


def try_compile_user_regex(
    pattern: str, flags: int = 0
) -> tuple[re.Pattern[str] | None, str | None]:
    """Compile *pattern* or return ``(None, reason)``.

    Returns:
        ``(compiled, None)`` on success, else ``(None, short error reason)``.
    """
    if len(pattern) > MAX_USER_REGEX_PATTERN_CHARS:
        return None, "pattern exceeds maximum length"
    try:
        return re.compile(pattern, flags), None
    except re.error as e:
        return None, str(e)
