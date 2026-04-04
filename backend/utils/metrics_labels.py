"""Helpers for sanitizing operation names for Prometheus labels."""

from __future__ import annotations

import re


def sanitize_operation_label(name: str | None, max_length: int = 100) -> str:
    """Sanitize an operation name to be safe for Prometheus label values.

    Replaces any character that is not alphanumeric or underscore with an underscore,
    collapses consecutive underscores, trims to max_length, and ensures a non-empty
    result (falls back to 'unknown'). If the sanitized name starts with a digit, we
    prefix it with 'op_'.
    """
    if not name:
        return 'unknown'
    s = str(name)
    s = re.sub('[^A-Za-z0-9_]', '_', s)
    s = re.sub('_+', '_', s)
    s = s[:max_length]
    s = s.strip('_')
    if not s:
        return 'unknown'
    if s[0].isdigit():
        s = f'op_{s}'
    return s
