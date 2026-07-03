"""Budgeted post-compact context re-injection."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.core.constants import (
    DEFAULT_POST_COMPACT_FILE_PREVIEW_CHARS,
    DEFAULT_POST_COMPACT_MAX_FILES,
    DEFAULT_POST_COMPACT_TOKEN_BUDGET,
)

if TYPE_CHECKING:
    from backend.ledger.event import Event
    from backend.orchestration.state.state import State


def build_post_compact_attachment_text(
    state: State | None,
    events: list[Event],
) -> str:
    """Build a compact re-injection block for the first prompt after compaction."""
    if state is None:
        return ''

    parts: list[str] = ['<POST_COMPACT_RESTORE>']
    budget = DEFAULT_POST_COMPACT_TOKEN_BUDGET

    goal_block = ''
    try:
        from backend.context.context_pipeline.goal_context import (
            build_goal_context_for_compaction,
        )

        goal_block = build_goal_context_for_compaction(state=state)
    except Exception:
        goal_block = ''
    if goal_block:
        parts.append('Goal context:')
        parts.append(goal_block)
        budget -= len(goal_block)

    task_block = _task_plan_block(state, budget)
    if task_block:
        parts.append(task_block)
        budget -= len(task_block)

    ac_block = _acceptance_criteria_block(budget)
    if ac_block:
        parts.append(ac_block)
        budget -= len(ac_block)

    files_block = _recent_files_block(state, events, budget)
    if files_block:
        parts.append(files_block)

    parts.append('</POST_COMPACT_RESTORE>')
    body = '\n'.join(parts)
    if body == '<POST_COMPACT_RESTORE>\n</POST_COMPACT_RESTORE>':
        return ''
    return body


def _task_plan_block(state: State, budget: int) -> str:
    try:
        from backend.context.compactor.pre_condensation_snapshot import load_snapshot

        snapshot = load_snapshot(state=state)
    except Exception:
        return ''
    if not isinstance(snapshot, dict):
        return ''
    task_plan = snapshot.get('task_plan')
    if not isinstance(task_plan, dict):
        return ''
    tasks = task_plan.get('tasks')
    if not isinstance(tasks, list):
        return ''
    lines = ['Active tasks:']
    for task in tasks[:6]:
        if not isinstance(task, dict):
            continue
        status = str(task.get('status', '') or '').lower()
        if status in {'done', 'completed', 'cancelled'}:
            continue
        desc = str(task.get('description', '') or '').strip()
        if desc:
            lines.append(f'- [{status or "?"}] {desc[:160]}')
    if len(lines) == 1:
        return ''
    block = '\n'.join(lines)
    return block[:budget] if len(block) > budget else block


def _acceptance_criteria_block(budget: int) -> str:
    try:
        from backend.core.criteria import AcceptanceCriteriaStore

        criteria = AcceptanceCriteriaStore().load_from_file()
    except Exception:
        return ''
    if not criteria:
        return ''
    lines = ['Open acceptance criteria:']
    for item in criteria[:6]:
        if not isinstance(item, dict):
            continue
        assertion = str(item.get('assertion', '') or '').strip()
        if assertion:
            lines.append(f'- {assertion[:180]}')
    if len(lines) == 1:
        return ''
    block = '\n'.join(lines)
    return block[:budget] if len(block) > budget else block


def _recent_files_block(state: State, events: list[Event], budget: int) -> str:
    paths: list[str] = []
    seen: set[str] = set()
    try:
        from backend.context.compactor.pre_condensation_snapshot import load_snapshot

        snapshot = load_snapshot(state=state)
        files = snapshot.get('files_touched', {}) if isinstance(snapshot, dict) else {}
        if isinstance(files, dict):
            for path in list(files.keys())[-DEFAULT_POST_COMPACT_MAX_FILES:]:
                if isinstance(path, str) and path not in seen:
                    seen.add(path)
                    paths.append(path)
    except Exception:
        paths = []
    if not paths:
        return ''
    lines = ['Recently touched files:']
    preview = DEFAULT_POST_COMPACT_FILE_PREVIEW_CHARS
    for path in paths[:DEFAULT_POST_COMPACT_MAX_FILES]:
        lines.append(f'- {path[:preview]}')
    block = '\n'.join(lines)
    return block[:budget] if len(block) > budget else block


__all__ = ['build_post_compact_attachment_text']
