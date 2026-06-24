"""Task tracking action/observation handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.ledger.action import TaskTrackingAction
from backend.ledger.observation import TaskTrackingObservation

if TYPE_CHECKING:
    from backend.cli.tui.renderer.mixins.event_processor import (
        RendererEventProcessorMixin,
    )


def _is_task_tracking_event(event: Any) -> bool:
    return isinstance(event, (TaskTrackingAction, TaskTrackingObservation))


def _apply_task_list_from_event(
    orch: 'RendererEventProcessorMixin',
    event: Any,
) -> bool:
    """Replace the in-memory task list when the event carries a definitive payload."""
    if not orch._should_replace_task_list_from_event(event):
        return False
    orch._task_list = list(getattr(event, 'task_list', []) or [])
    orch._last_task_sidebar_signature = None
    return True


def _schedule_eager_tasks_sidebar_refresh(orch: 'RendererEventProcessorMixin') -> None:
    """Paint the tasks sidebar on the Textual loop without waiting for drain."""

    def _refresh() -> None:
        try:
            orch._refresh_tasks_sidebar()
        except Exception:
            pass

    try:
        orch._loop.call_soon_threadsafe(_refresh)
    except RuntimeError:
        pass


def eager_apply_task_tracking_event(
    orch: 'RendererEventProcessorMixin',
    event: Any,
) -> bool:
    """Apply task-list side effects as soon as the event is enqueued."""
    if not _is_task_tracking_event(event):
        return False
    updated = _apply_task_list_from_event(orch, event)
    if updated:
        _schedule_eager_tasks_sidebar_refresh(orch)
    return updated


def _handle_task_tracking_observation(
    orch: 'RendererEventProcessorMixin', event: TaskTrackingObservation
) -> None:
    if _apply_task_list_from_event(orch, event):
        orch._refresh_display()


def _handle_task_tracking_action(
    orch: 'RendererEventProcessorMixin', event: TaskTrackingAction
) -> None:
    if _apply_task_list_from_event(orch, event):
        orch._refresh_display()
