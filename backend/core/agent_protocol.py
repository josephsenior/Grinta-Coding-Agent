"""Optional task-tracker helpers for Agent/Plan runs."""

from __future__ import annotations

from typing import Any

from backend.core.interaction_modes import (
    AGENT_MODE,
    PLAN_MODE,
    normalize_interaction_mode,
)
from backend.core.task_status import (
    ACTIVE_TASK_STATUSES,
    TASK_STATUS_BLOCKED,
    TASK_STATUS_SKIPPED,
    TERMINAL_TASK_STATUSES,
)

TRACKER_CREATED_KEY = '__agent_protocol_tracker_created'
VALIDATOR_FAILURE_COUNTER_KEY = '__agent_protocol_validator_failure_counter'

ABANDONED_RETRY_PROMPT = 'Run paused because the model returned no usable output.'


PROTOCOL_MODES = frozenset({AGENT_MODE, PLAN_MODE})


def is_protocol_mode(mode: object) -> bool:
    """Return True when tracker-driven protocol enforcement should apply."""
    return normalize_interaction_mode(mode) in PROTOCOL_MODES


def is_agent_mode(mode: object) -> bool:
    """Return True when protocol enforcement should apply for Agent mode."""
    return normalize_interaction_mode(mode) == AGENT_MODE


def _extra(state: object | None) -> dict[str, Any]:
    if state is None:
        return {}
    extra = getattr(state, 'extra_data', None)
    if isinstance(extra, dict):
        return extra
    try:
        state.extra_data = {}
        return state.extra_data
    except Exception:
        return {}


def _set_extra(state: object | None, key: str, value: Any, *, source: str) -> None:
    extra = _extra(state)
    if not extra and state is None:
        return
    extra[key] = value
    set_extra = getattr(state, 'set_extra', None)
    if callable(set_extra):
        try:
            set_extra(key, value, source=source)
        except Exception:
            pass


def _step_field(step: Any, name: str, default: Any = None) -> Any:
    if isinstance(step, dict):
        return step.get(name, default)
    return getattr(step, name, default)


def _plan_steps(state: object | None) -> list[Any]:
    plan = getattr(state, 'plan', None) if state is not None else None
    steps = getattr(plan, 'steps', None) if plan is not None else None
    return steps if isinstance(steps, list) else []


def iter_task_steps(steps: list[Any]) -> list[Any]:
    """Flatten a task list, preserving parent-before-child order."""
    flattened: list[Any] = []
    for step in steps or []:
        flattened.append(step)
        subtasks = _step_field(step, 'subtasks', []) or []
        if isinstance(subtasks, list):
            flattened.extend(iter_task_steps(subtasks))
    return flattened


def current_task_steps(state: object | None) -> list[Any]:
    """Return the flattened in-memory active plan steps."""
    return iter_task_steps(_plan_steps(state))


def task_status(step: Any) -> str:
    return str(_step_field(step, 'status', '') or '').strip().lower()


def task_description(step: Any) -> str:
    return str(_step_field(step, 'description', '') or '').strip()


def task_id(step: Any) -> str:
    return str(_step_field(step, 'id', '') or '').strip()


def mark_tracker_created(state: object | None, *, source: str = '') -> None:
    """Record that the agent committed to a structured task run."""
    _set_extra(
        state,
        TRACKER_CREATED_KEY,
        True,
        source=source or 'agent_protocol.mark_tracker_created',
    )


def tracker_created(state: object | None) -> bool:
    """Return True once the agent has committed via task tracking."""
    extra = _extra(state)
    if bool(extra.get(TRACKER_CREATED_KEY)):
        return True
    return bool(current_task_steps(state))


def work_remains(state: object | None) -> bool:
    """The only active-work predicate: any tracker item todo/in_progress."""
    if not tracker_created(state):
        return False
    return any(task_status(step) in ACTIVE_TASK_STATUSES for step in current_task_steps(state))


def tracker_terminal(state: object | None) -> bool:
    """True when a created tracker has tasks and every task is terminal."""
    if not tracker_created(state):
        return False
    steps = current_task_steps(state)
    if not steps:
        return False
    return all(task_status(step) in TERMINAL_TASK_STATUSES for step in steps)


def reset_terminal_cycle(state: object | None) -> None:
    _ = state


def validator_failures(state: object | None) -> int:
    try:
        return max(0, int(_extra(state).get(VALIDATOR_FAILURE_COUNTER_KEY, 0) or 0))
    except Exception:
        return 0


def increment_validator_failures(state: object | None) -> int:
    count = validator_failures(state) + 1
    _set_extra(
        state,
        VALIDATOR_FAILURE_COUNTER_KEY,
        count,
        source='agent_protocol.increment_validator_failures',
    )
    return count


def reset_validator_failures(state: object | None) -> None:
    _set_extra(
        state,
        VALIDATOR_FAILURE_COUNTER_KEY,
        0,
        source='agent_protocol.reset_validator_failures',
    )


def skipped_or_blocked_steps(state: object | None) -> list[Any]:
    return [
        step
        for step in current_task_steps(state)
        if task_status(step) in {TASK_STATUS_SKIPPED, TASK_STATUS_BLOCKED}
    ]


def prepare_next_agent_step(state: object | None, mode: object) -> None:
    """No-op retained for older service wiring."""
    _ = (state, mode)
