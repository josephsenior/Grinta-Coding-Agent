"""Policy for late runtime error status after user terminal states.

Subprocess / memory callbacks can fire after ``stop()`` or successful finish.
Those diagnostics are recorded via ``set_last_error`` but must not call
``set_agent_state_to(ERROR)`` when the agent is already parked or finished,
otherwise :class:`InvalidStateTransitionError` is raised and semantics blur
(WAL / reconnect: ``STOPPED`` is not a failure).
"""

from __future__ import annotations

from backend.core.enums import AgentState
from backend.core.logger import app_logger as logger

# Agent states where a late runtime ``error`` status must not promote to ERROR.
TERMINALS_NO_LATE_RUNTIME_ERROR_PROMOTION: frozenset[AgentState] = frozenset(
    (AgentState.STOPPED, AgentState.FINISHED)
)


def should_skip_agent_error_transition_for_runtime_callback(controller: object) -> bool:
    """Return True if we must not schedule ``set_agent_state_to(ERROR)``."""
    get_state = getattr(controller, 'get_agent_state', None)
    if not callable(get_state):
        return False
    try:
        current = get_state()
    except Exception:
        logger.debug(
            'get_agent_state failed in runtime late-error guard', exc_info=True
        )
        return False
    if current in TERMINALS_NO_LATE_RUNTIME_ERROR_PROMOTION:
        logger.info(
            'Runtime error callback: skipping agent ERROR transition while state is %s',
            getattr(current, 'value', current),
        )
        return True
    return False
