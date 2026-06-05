"""Agent/Plan task-run protocol helpers.

The protocol is intentionally derived from the task tracker.  Agent and Plan
modes stay conversational until the agent explicitly creates or updates a
tracker; after that, unfinished tracker items are the only source of "work
remains" truth.
"""

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
PROSE_ATTEMPT_COUNTER_KEY = '__agent_protocol_prose_attempt_counter'
PENDING_DIRECTIVE_KEY = '__agent_protocol_pending_directive'
TERMINAL_FINISH_NUDGE_SENT_KEY = '__agent_protocol_terminal_finish_nudge_sent'
SELF_EXTENSION_COUNTER_KEY = '__agent_protocol_self_extension_counter'
ABANDONED_KEY = '__agent_protocol_abandoned'
VALIDATOR_FAILURE_COUNTER_KEY = '__agent_protocol_validator_failure_counter'

CONTINUATION_NUDGE = 'Continue with a tool call, finish, or communicate_with_user.'
TERMINAL_FINISH_DIRECTIVE = (
    'All tasks complete. Call finish with your summary. '
    'Note any skipped or blocked items in your summary.'
)
ABANDONED_RETRY_PROMPT = "Run didn't complete — want to continue from where it left off?"


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


def reset_prose_attempts(state: object | None) -> None:
    _set_extra(
        state,
        PROSE_ATTEMPT_COUNTER_KEY,
        0,
        source='agent_protocol.reset_prose_attempts',
    )


def prose_attempts(state: object | None) -> int:
    try:
        return max(0, int(_extra(state).get(PROSE_ATTEMPT_COUNTER_KEY, 0) or 0))
    except Exception:
        return 0


def increment_prose_attempts(state: object | None) -> int:
    count = prose_attempts(state) + 1
    _set_extra(
        state,
        PROSE_ATTEMPT_COUNTER_KEY,
        count,
        source='agent_protocol.increment_prose_attempts',
    )
    return count


def set_pending_directive(
    state: object | None, directive: str, *, source: str = ''
) -> None:
    _set_extra(
        state,
        PENDING_DIRECTIVE_KEY,
        directive,
        source=source or 'agent_protocol.set_pending_directive',
    )


def pop_pending_directive(state: object | None) -> str:
    extra = _extra(state)
    value = str(extra.pop(PENDING_DIRECTIVE_KEY, '') or '')
    return value.strip()


def terminal_nudge_sent(state: object | None) -> bool:
    return bool(_extra(state).get(TERMINAL_FINISH_NUDGE_SENT_KEY))


def set_terminal_nudge_sent(state: object | None, value: bool) -> None:
    _set_extra(
        state,
        TERMINAL_FINISH_NUDGE_SENT_KEY,
        bool(value),
        source='agent_protocol.set_terminal_nudge_sent',
    )


def reset_terminal_cycle(state: object | None) -> None:
    set_terminal_nudge_sent(state, False)
    _set_extra(
        state,
        SELF_EXTENSION_COUNTER_KEY,
        0,
        source='agent_protocol.reset_terminal_cycle',
    )


def self_extension_count(state: object | None) -> int:
    try:
        return max(0, int(_extra(state).get(SELF_EXTENSION_COUNTER_KEY, 0) or 0))
    except Exception:
        return 0


def increment_self_extension(state: object | None) -> int:
    count = self_extension_count(state) + 1
    _set_extra(
        state,
        SELF_EXTENSION_COUNTER_KEY,
        count,
        source='agent_protocol.increment_self_extension',
    )
    return count


def mark_abandoned(state: object | None) -> None:
    _set_extra(
        state,
        ABANDONED_KEY,
        True,
        source='agent_protocol.mark_abandoned',
    )


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
    """Inject pending protocol directives before the next Agent/Plan LLM step."""
    if state is None or not is_protocol_mode(mode):
        return

    directive = pop_pending_directive(state)
    if not directive and tracker_terminal(state) and not terminal_nudge_sent(state):
        directive = TERMINAL_FINISH_DIRECTIVE
        set_terminal_nudge_sent(state, True)

    if not directive:
        return
    set_planning_directive = getattr(state, 'set_planning_directive', None)
    if callable(set_planning_directive):
        set_planning_directive(directive, source='agent_protocol.prepare_next_agent_step')
