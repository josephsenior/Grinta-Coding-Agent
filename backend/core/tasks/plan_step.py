"""Plan-step payload normalization (pure functions, no orchestration deps)."""

from __future__ import annotations

from typing import Any

from backend.core.tasks.task_status import (
    TASK_STATUS_DONE,
    TASK_STATUS_TODO,
    normalize_task_status,
)


def _normalize_plan_step_status(raw_status: Any) -> str:
    try:
        return normalize_task_status(raw_status, default=TASK_STATUS_TODO)
    except ValueError as exc:
        raise TypeError(str(exc)) from exc


def _normalize_plan_step_subtasks(step: dict) -> list:
    subtasks = step.get('subtasks', [])
    if subtasks is None:
        subtasks = []
    if not isinstance(subtasks, list):
        msg = "Plan step 'subtasks' must be a list"
        raise TypeError(msg)
    return subtasks


def _coerce_plan_step_tags(raw_tags: Any) -> list:
    if raw_tags is None:
        return []
    if isinstance(raw_tags, str):
        return [t.strip() for t in raw_tags.split(',') if t.strip()]
    if isinstance(raw_tags, list):
        return raw_tags
    return [raw_tags]


def _normalize_plan_step_tags(step: dict) -> list[str]:
    return [
        str(t) for t in _coerce_plan_step_tags(step.get('tags', [])) if t is not None
    ]


def _resolve_plan_step_status(step: dict, normalized_subtasks: list) -> str:
    resolved_status = _normalize_plan_step_status(step.get('status'))
    if normalized_subtasks and all(
        s['status'] == TASK_STATUS_DONE for s in normalized_subtasks
    ):
        resolved_status = TASK_STATUS_DONE
    return resolved_status


def _build_plan_step_result(
    step: dict,
    fallback_id: str,
    resolved_status: str,
    normalized_subtasks: list,
    tags: list[str],
) -> dict[str, Any]:
    return {
        'id': str(step.get('id') or fallback_id),
        'description': str(step.get('description') or 'Untitled step'),
        'status': resolved_status,
        'result': step.get('result'),
        'tags': [str(tag) for tag in tags],
        'subtasks': normalized_subtasks,
    }


def normalize_plan_step_payload(step: Any, idx: int | None = None) -> dict[str, Any]:
    """Normalize plan/task-tracker step payloads to the canonical schema."""
    if not isinstance(step, dict):
        msg = f'Plan step must be a dictionary, got {type(step)}'
        raise TypeError(msg)

    fallback_id = f'step-{idx}' if idx is not None else 'step'
    subtasks = _normalize_plan_step_subtasks(step)
    tags = _normalize_plan_step_tags(step)
    normalized_subtasks = [
        normalize_plan_step_payload(subtask, i + 1)
        for i, subtask in enumerate(subtasks)
    ]
    resolved_status = _resolve_plan_step_status(step, normalized_subtasks)

    return _build_plan_step_result(
        step, fallback_id, resolved_status, normalized_subtasks, tags
    )
