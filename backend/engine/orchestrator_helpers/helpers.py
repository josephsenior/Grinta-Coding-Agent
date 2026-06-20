"""Top-level helper functions used by :mod:`backend.engine.orchestrator`."""

from __future__ import annotations

import re
from typing import Any


def _safe_plain_text_count(executor: Any) -> int:
    """Read the executor's plain-text counter defensively.

    Some unit tests substitute the executor with a ``MagicMock`` that does
    not have a real ``_consecutive_plain_text_blocks`` attribute, so
    ``getattr`` would return another ``MagicMock`` and the ``> 0`` check
    would raise ``TypeError``. Treat any non-int value as zero.
    """
    raw = getattr(executor, '_consecutive_plain_text_blocks', 0)
    return raw if isinstance(raw, int) else 0


def _should_reset_plain_text_count(actions: list[Any]) -> bool:
    """Reset prose drift only after real work/finish, not status cards."""
    if not actions:
        return False
    if all(bool(getattr(action, 'protocol_status', False)) for action in actions):
        return False
    return True


def _normalize_recoverable_error_signature(e: Exception) -> str:
    """Normalize error signature for reliable loop detection.

    Extracts error type and key identifiers (tool name, error category)
    while ignoring variable message content that would prevent matching.
    """
    error_type = type(e).__name__
    msg = str(e).strip()

    tool_match = re.search(r"Tool [`'](\w+)[`']?", msg)
    tool_name = tool_match.group(1) if tool_match else ''

    category_match = re.search(r'\[([A-Z_]+)\]', msg)
    category = category_match.group(1) if category_match else ''

    parts = [error_type]
    if category:
        parts.append(category)
    if tool_name:
        parts.append(tool_name)
    return ':'.join(parts)


def _graceful_shrink_large_cmd_outputs(history: list[Any]) -> int:
    """Truncate oversized command outputs; returns count mutated."""
    from backend.ledger.observation import (
        CmdOutputObservation,
    )

    shrunk = 0
    for ev in history:
        if not isinstance(ev, CmdOutputObservation):
            continue
        content = getattr(ev, 'content', '') or ''
        if len(content) <= 2000:
            continue
        head = content[:800]
        tail = content[-800:]
        ev.content = (
            f'{head}\n... [graceful-degradation truncated '
            f'{len(content) - 1600} chars] ...\n{tail}'
        )
        shrunk += 1
    return shrunk


def _graceful_trim_old_error_observations(history: list[Any]) -> int:
    """Replace oldest ErrorObservations beyond the last five; returns count mutated."""
    from backend.ledger.observation.error import ErrorObservation

    errors = [i for i, ev in enumerate(history) if isinstance(ev, ErrorObservation)]
    dropped = 0
    if len(errors) <= 5:
        return dropped
    for idx in errors[:-5]:
        ev = history[idx]
        if not isinstance(ev, ErrorObservation):
            continue
        msg = (ev.content or '')[:200]
        ev.content = f'[graceful-degradation: error trimmed] {msg}'
        dropped += 1
    return dropped
