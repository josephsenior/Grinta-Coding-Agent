"""Task tracking action/observation handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.ledger.action import TaskTrackingAction
from backend.ledger.observation import TaskTrackingObservation

if TYPE_CHECKING:
    from backend.cli.tui.renderer.mixins.event_processor import (
        _AppRendererEventProcessorMixin,
    )


def _handle_task_tracking_observation(
    orch: '_AppRendererEventProcessorMixin', event: TaskTrackingObservation
) -> None:
    if orch._should_replace_task_list_from_event(event):
        orch._task_list = list(getattr(event, 'task_list', []) or [])
        orch._refresh_display()


def _handle_task_tracking_action(
    orch: '_AppRendererEventProcessorMixin', event: TaskTrackingAction
) -> None:
    if orch._should_replace_task_list_from_event(event):
        orch._task_list = list(getattr(event, 'task_list', []) or [])
        orch._refresh_display()
