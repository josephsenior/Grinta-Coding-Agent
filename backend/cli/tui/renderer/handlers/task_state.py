"""Canonical task-state handlers that keep the Tasks sidebar current."""

from __future__ import annotations

from typing import TYPE_CHECKING

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


def _handle_task_state_observation(
    orch: 'RendererEventProcessorMixin', event: TaskStateObservation
) -> None:
    state = getattr(event, 'state', None)
    plan = state.get('plan') if isinstance(state, dict) else None
    tasks = plan.get('tasks') if isinstance(plan, dict) else None
    if not isinstance(tasks, list):
        return

    orch._task_list = list(tasks)
    orch._last_task_sidebar_signature = None
    orch._refresh_tasks_sidebar()
