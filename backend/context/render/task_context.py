"""Composable renderers for goal context, task scope, and acceptance gates."""

from __future__ import annotations

from typing import Any

_DONE_STATUSES = frozenset({'done', 'completed', 'cancelled'})

EMPTY_TASK_PLAN_HINT = '(no durable tasks recorded — use task_state(set, tasks=[...]) for substantial multi-step work)'
EMPTY_ACCEPTANCE_GATES_HINT = '(no durable contract conditions recorded — use task_state(set) when explicit outcomes must persist)'


def cap_line(text: str, limit: int) -> str:
    cleaned = ' '.join(str(text or '').split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + '...'


def render_goal_header(canonical: object | None) -> list[str]:
    """Render objective, directive, and next action from canonical state."""
    if canonical is None:
        return []
    lines: list[str] = []
    objective = str(getattr(canonical, 'objective', '') or '').strip()
    if objective:
        lines.append(f'- Objective: {cap_line(objective, 240)}')
    directive = str(getattr(canonical, 'latest_directive', '') or '').strip()
    if directive and directive != objective:
        lines.append(f'- Latest directive: {cap_line(directive, 200)}')
    next_action = str(getattr(canonical, 'next_action', '') or '').strip()
    if next_action:
        lines.append(f'- Next action: {cap_line(next_action, 200)}')
    return lines


def _task_description(task: dict[str, Any]) -> str:
    for key in ('description', 'title', 'task', 'content', 'name'):
        value = task.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ''


def render_task_plan(
    tasks: object,
    *,
    max_items: int = 12,
    header: str = '- Task plan:',
    desc_limit: int = 160,
    only_open: bool = False,
    show_empty: bool = False,
    empty_hint: str = EMPTY_TASK_PLAN_HINT,
) -> list[str]:
    """Render task plan bullets with stable ids from snapshot dict or task list."""
    task_items: list[dict[str, Any]] = []
    if isinstance(tasks, dict):
        raw = tasks.get('tasks')
        if isinstance(raw, list):
            task_items = [item for item in raw if isinstance(item, dict)]
    elif isinstance(tasks, list):
        task_items = [item for item in tasks if isinstance(item, dict)]

    if not task_items:
        if show_empty:
            return [header, f'  {empty_hint}']
        return []

    lines = [header]
    for task in task_items[:max_items]:
        status = str(task.get('status', '') or '').strip().lower()
        if only_open and status in _DONE_STATUSES:
            continue
        desc = _task_description(task)
        if not desc:
            continue
        task_id = str(task.get('id', '') or '').strip()
        id_part = f' (id={task_id})' if task_id else ''
        lines.append(f'  - [{status or "?"}]{id_part} {cap_line(desc, desc_limit)}')
    if len(lines) > 1:
        return lines
    if show_empty:
        return [header, f'  {empty_hint}']
    return []


def render_active_scope(
    tasks: object,
    *,
    max_items: int = 8,
    header: str = '- Active scope:',
    desc_limit: int = 160,
) -> list[str]:
    """Render in-progress task scope from snapshot dict or task list."""
    return render_task_plan(
        tasks,
        max_items=max_items,
        header=header,
        desc_limit=desc_limit,
        only_open=True,
    )


def render_acceptance_gates(
    criteria: object,
    *,
    max_items: int = 10,
    header: str = '- Acceptance gates:',
    assertion_limit: int = 180,
    evidence_limit: int = 80,
    show_empty: bool = False,
    empty_hint: str = EMPTY_ACCEPTANCE_GATES_HINT,
) -> list[str]:
    """Render open acceptance criteria assertions."""
    if not isinstance(criteria, list) or not criteria:
        if show_empty:
            return [header, f'  {empty_hint}']
        return []
    lines = [header]
    for item in criteria[:max_items]:
        if not isinstance(item, dict):
            continue
        assertion = str(item.get('assertion', '') or '').strip()
        if not assertion:
            continue
        evidence = str(item.get('evidence', '') or '').strip()
        suffix = (
            f' (evidence: {cap_line(evidence, evidence_limit)})' if evidence else ''
        )
        criterion_id = str(item.get('id', '') or '').strip()
        label = f'[{criterion_id}] ' if criterion_id else ''
        lines.append(f'  - {label}{cap_line(assertion, assertion_limit)}{suffix}')
    return lines if len(lines) > 1 else []


__all__ = [
    'EMPTY_ACCEPTANCE_GATES_HINT',
    'EMPTY_TASK_PLAN_HINT',
    'cap_line',
    'render_acceptance_gates',
    'render_active_scope',
    'render_goal_header',
    'render_task_plan',
]
