"""Helpers to correlate LLM prompt shape (per astep) with CLI reasoning updates."""

from __future__ import annotations

import time
from collections import Counter
from typing import Any

from backend.core.constants import APP_DEBUG_REASONING_ASTEP
from backend.core.logging.session_event_logger import emit_session_event

_CURRENT_ASTEP_ID = 0


def env_prompt_roles_debug() -> bool:
    return True


def env_reasoning_astep_debug() -> bool:
    return APP_DEBUG_REASONING_ASTEP


def any_prompt_or_reasoning_debug() -> bool:
    return env_prompt_roles_debug() or env_reasoning_astep_debug()


def mark_astep_begin() -> int:
    """Call once at the start of each orchestrator LLM step (before build_messages)."""
    global _CURRENT_ASTEP_ID
    _CURRENT_ASTEP_ID += 1
    return _CURRENT_ASTEP_ID


def current_astep_id() -> int:
    return _CURRENT_ASTEP_ID


def log_prompt_roles_after_build_messages(
    messages: list[Any],
    *,
    astep_id: int,
    condensed_event_count: int,
    pending_condensation: bool,
    history_event_count: int,
) -> None:
    roles: Counter[str] = Counter()
    for m in messages:
        r = getattr(m, 'role', None)
        roles[str(r) if r is not None else '?'] += 1
    assistant_with_tools = sum(
        1
        for m in messages
        if getattr(m, 'role', None) == 'assistant' and getattr(m, 'tool_calls', None)
    )
    emit_session_event(
        'PROMPT_SHAPE',
        {
            'astep_id': astep_id,
            'roles': dict(roles),
            'condensed_events': condensed_event_count,
            'pending_condensation': pending_condensation,
            'history_events': history_event_count,
            'assistant_with_tool_calls': assistant_with_tools,
            'tool_msgs': roles.get('tool', 0),
            'user_msgs': roles.get('user', 0),
        },
    )


def log_reasoning_transition(kind: str, detail: str = '') -> None:
    if not env_reasoning_astep_debug():
        return
    from backend.core.logging.logger import app_logger as logger

    preview = (detail or '')[:160]
    logger.info(
        'APP_DEBUG_REASONING_ASTEP t=%.3f astep_id=%s kind=%s detail=%r',
        time.monotonic(),
        current_astep_id(),
        kind,
        preview,
    )
