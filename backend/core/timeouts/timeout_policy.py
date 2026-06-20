"""Shared timeout budgets for orchestration pending actions and sync/async bridges.

Keeps ``PendingActionService`` floors and ``LocalRuntimeInProcess.call_async_from_sync``
budgets aligned for ``CmdRunAction`` so reordering mixins cannot undershoot the shell
hard limit relative to the controller.
"""

from __future__ import annotations

from typing import Any

from backend.core.constants import (
    CMD_PENDING_ACTION_TIMEOUT_FLOOR,
    TOOL_BRIDGE_TIMEOUT_BUFFER,
)


def cmd_run_timeout_candidates(base: float, action: Any) -> list[float]:
    """Wall-clock candidates for ``CmdRunAction`` (seconds), same inputs as pending policy."""
    candidates = [float(base), float(CMD_PENDING_ACTION_TIMEOUT_FLOOR)]
    action_timeout = getattr(action, 'timeout', None)
    try:
        parsed = float(action_timeout) if action_timeout is not None else None
    except (TypeError, ValueError):
        parsed = None
    if parsed is not None and parsed > 0:
        candidates.append(parsed)
    return candidates


def effective_cmd_run_pending_timeout_seconds(base: float, action: Any) -> float:
    """Effective pending watchdog window for ``CmdRunAction`` (matches PendingActionService)."""
    return max(cmd_run_timeout_candidates(base, action))


def cmd_run_sync_bridge_timeout_seconds(action: Any) -> float:
    """Outer ``call_async_from_sync`` budget for ``CmdRunAction.run``.

    Uses ``action.timeout + TOOL_BRIDGE_TIMEOUT_BUFFER`` when the action carries a
    positive timeout (including the 600s safety net set by
    :meth:`backend.execution.command_timeout.CommandTimeoutMixin._set_action_timeout`).
    Otherwise uses :data:`CMD_PENDING_ACTION_TIMEOUT_FLOOR` plus the same buffer so the
    bridge matches the default shell hard limit without relying on a 120s fallback.
    """
    action_timeout = getattr(action, 'timeout', None)
    try:
        parsed = float(action_timeout) if action_timeout is not None else None
    except (TypeError, ValueError):
        parsed = None
    if parsed is not None and parsed > 0:
        return parsed + float(TOOL_BRIDGE_TIMEOUT_BUFFER)
    return float(CMD_PENDING_ACTION_TIMEOUT_FLOOR) + float(TOOL_BRIDGE_TIMEOUT_BUFFER)


__all__ = [
    'cmd_run_sync_bridge_timeout_seconds',
    'cmd_run_timeout_candidates',
    'effective_cmd_run_pending_timeout_seconds',
]
