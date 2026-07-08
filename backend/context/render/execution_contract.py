"""JSON-backed execution contract projected into every agent prompt."""

from __future__ import annotations

from typing import Any

from backend.context.render.task_context import (
    render_acceptance_gates,
    render_goal_header,
    render_task_plan,
)
from backend.core.constants import DEFAULT_EXECUTION_CONTRACT_MAX_CHARS
from backend.core.logging.logger import app_logger as logger


def build_execution_contract(
    *,
    state: object | None = None,
    snapshot: dict[str, Any] | None = None,
    canonical: object | None = None,
    max_chars: int = DEFAULT_EXECUTION_CONTRACT_MAX_CHARS,
    only_open_tasks: bool = False,
    include_goal_header: bool = True,
    show_empty_states: bool = False,
) -> str:
    """Build the live task plan and acceptance-gates block from JSON stores."""
    lines = build_execution_contract_lines(
        state=state,
        snapshot=snapshot,
        canonical=canonical,
        only_open_tasks=only_open_tasks,
        include_goal_header=include_goal_header,
        show_empty_states=show_empty_states,
    )
    if not lines:
        return ''
    body = '\n'.join(lines).strip()
    if len(body) > max_chars:
        body = body[: max_chars - 3].rstrip() + '...'
    return body


def build_execution_contract_lines(
    *,
    state: object | None = None,
    snapshot: dict[str, Any] | None = None,
    canonical: object | None = None,
    only_open_tasks: bool = False,
    include_goal_header: bool = True,
    show_empty_states: bool = False,
) -> list[str]:
    """Return bullet lines for objective, task plan, and acceptance gates."""
    if canonical is None and state is not None:
        canonical = _load_canonical_safe(state)
    if snapshot is None and state is not None:
        snapshot = _load_snapshot_safe(state)

    lines: list[str] = []
    if include_goal_header:
        lines.extend(render_goal_header(canonical))

    task_plan = _resolve_task_plan(snapshot)
    header = '- Task plan:' if not only_open_tasks else '- Active scope:'
    if task_plan is not None:
        lines.extend(
            render_task_plan(
                task_plan,
                only_open=only_open_tasks,
                header=header,
                show_empty=show_empty_states,
            )
        )
    elif show_empty_states:
        lines.extend(
            render_task_plan(
                [],
                header=header,
                show_empty=True,
            )
        )

    lines.extend(_acceptance_criteria_lines(show_empty=show_empty_states))
    return lines


def _resolve_task_plan(snapshot: dict[str, Any] | None) -> dict[str, Any] | list[Any] | None:
    if isinstance(snapshot, dict):
        raw_plan = snapshot.get('task_plan')
        if isinstance(raw_plan, dict) and raw_plan.get('tasks'):
            return raw_plan
    try:
        from backend.core.task_tracker import TaskTracker

        tasks = TaskTracker().load_from_file()
        if tasks:
            return {'tasks': tasks}
    except Exception:
        logger.debug('Execution contract task plan load failed', exc_info=True)
    return None


def _load_snapshot_safe(state: object) -> dict[str, Any] | None:
    try:
        from backend.context.compactor.pre_condensation_snapshot import load_snapshot

        raw = load_snapshot(state=state)  # type: ignore[arg-type]
        return raw if isinstance(raw, dict) else None
    except Exception:
        logger.debug('Failed to load snapshot for execution contract', exc_info=True)
        return None


def _load_canonical_safe(state: object | None) -> object | None:
    if state is None:
        return None
    try:
        from backend.context.canonical_state import load_canonical_state

        return load_canonical_state(state=state)  # type: ignore[arg-type]
    except Exception:
        return None


def _acceptance_criteria_lines(*, show_empty: bool = False) -> list[str]:
    try:
        from backend.core.criteria import AcceptanceCriteriaStore

        criteria = AcceptanceCriteriaStore().load_from_file()
        return render_acceptance_gates(criteria, show_empty=show_empty)
    except Exception:
        return []


__all__ = [
    'build_execution_contract',
    'build_execution_contract_lines',
]
