"""Canonical task-state handlers for the sidebar and structured transcript card."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.ledger.action import TaskStateAction
from backend.ledger.observation import TaskStateObservation

if TYPE_CHECKING:
    from backend.cli.tui.renderer.mixins.event_processor import (
        RendererEventProcessorMixin,
    )


def _handle_task_state_action(
    orch: 'RendererEventProcessorMixin', event: TaskStateAction
) -> None:
    """Task-state commands are represented only by the persistent sidebar."""
    del orch, event


def _task_state_tasks(state: Any) -> list[Any] | None:
    plan = state.get('plan') if isinstance(state, dict) else None
    tasks = plan.get('tasks') if isinstance(plan, dict) else None
    return list(tasks) if isinstance(tasks, list) else None


def _task_state_card_metadata(
    state: Any, event: TaskStateObservation
) -> tuple[str, int | None]:
    contract = state.get('contract') if isinstance(state, dict) else None
    objective = (
        str(contract.get('objective') or '').strip()
        if isinstance(contract, dict)
        else ''
    )
    revision = getattr(event, 'revision', None)
    if revision is None and isinstance(state, dict):
        revision = state.get('revision')
    return objective, revision if isinstance(revision, int) else None


def _handle_task_state_observation(
    orch: 'RendererEventProcessorMixin', event: TaskStateObservation
) -> None:
    state = getattr(event, 'state', None)
    tasks = _task_state_tasks(state)
    if tasks is not None:
        orch._task_list = list(tasks)
        orch._last_task_sidebar_signature = None
        orch._refresh_tasks_sidebar()

    objective, revision = _task_state_card_metadata(state, event)

    from backend.cli.tui.widgets.scan_line import TaskStateCard

    orch._append_scan_line_card(
        TaskStateCard(
            str(getattr(event, 'command', '') or 'view'),
            revision=revision,
            objective=objective,
            tasks=list(tasks or []),
        )
    )
