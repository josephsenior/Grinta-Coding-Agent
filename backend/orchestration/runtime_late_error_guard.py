"""Guard against promoting late runtime errors after terminal agent states."""

from __future__ import annotations

from typing import Any

from backend.core.schemas import AgentState

TERMINALS_NO_LATE_RUNTIME_ERROR_PROMOTION = frozenset(
    {
        AgentState.STOPPED,
        AgentState.FINISHED,
    }
)


def should_skip_agent_error_transition_for_runtime_callback(ctrl: Any) -> bool:
    """Return True when a late runtime callback should not force ERROR state."""
    get_state = getattr(ctrl, 'get_agent_state', None)
    if not callable(get_state):
        return False
    state = get_state()
    return state in TERMINALS_NO_LATE_RUNTIME_ERROR_PROMOTION
