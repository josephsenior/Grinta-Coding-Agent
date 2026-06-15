"""Delegate task action/observation handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.cli.event_rendering.unified_renderer import ActivityRenderer
from backend.cli.tui.renderer.helpers.delegate import (
    build_delegate_preview,
    resolve_delegate_card_detail,
    resolve_delegate_task_and_worker,
)
from backend.ledger.action import DelegateTaskAction
from backend.ledger.observation import DelegateTaskObservation

if TYPE_CHECKING:
    from backend.cli.tui.renderer.mixins.event_processor import (
        RendererEventProcessorMixin,
    )


def _register_parallel_worker_tasks(
    orch: 'RendererEventProcessorMixin',
    event: DelegateTaskAction,
) -> None:
    for item in list(getattr(event, 'parallel_tasks', []) or []):
        task_desc = orch._summarize_worker_task(
            str(item.get('task_description') or 'delegated task')
        )
        orch._active_worker_tasks.append(task_desc)


def _record_delegate_result(
    orch: 'RendererEventProcessorMixin',
    resolved_task: str,
    success: bool,
) -> None:
    if success:
        orch._worker_completed += 1
    else:
        orch._worker_failed += 1
    if resolved_task:
        prefix = 'ok' if success else 'fail'
        orch._worker_recent_results.append(f'{prefix}: {resolved_task}')
    orch._sync_worker_strip()


def _update_or_write_delegate_card(
    orch: 'RendererEventProcessorMixin',
    card: Any,
    resolved_task: str,
    success: bool,
    preview: str | None,
) -> None:
    pending = orch._pending_delegate_card
    if pending is not None:
        status = 'ok' if success else 'err'
        outcome = 'completed' if success else 'failed'
        orch._update_activity_card_outcome(
            pending,
            status=status,
            outcome=outcome,
            extra_content=preview,
            operation_label=f'Delegated {resolved_task}'.strip(),
        )
        orch._pending_delegate_card = None
    else:
        orch._write_card(card)


def _handle_delegate_task_action(
    orch: 'RendererEventProcessorMixin', event: DelegateTaskAction
) -> None:
    task, worker = resolve_delegate_task_and_worker(event)
    if getattr(event, 'parallel_tasks', None):
        _register_parallel_worker_tasks(orch, event)
    else:
        orch._active_worker_tasks.append(orch._summarize_worker_task(task))
    orch._sync_worker_strip()
    card = ActivityRenderer.delegation(task, worker)
    widget = orch._write_card(card)
    orch._pending_delegate_card = widget


def _handle_delegate_task_observation(
    orch: 'RendererEventProcessorMixin', event: DelegateTaskObservation
) -> None:
    content, error_message = resolve_delegate_card_detail(event)
    success = bool(getattr(event, 'success', True))
    resolved_task = (
        orch._active_worker_tasks.pop(0)
        if orch._active_worker_tasks
        else 'delegated task'
    )
    _record_delegate_result(orch, resolved_task, success)
    detail = error_message or content
    card = ActivityRenderer.delegation(
        resolved_task,
        result=detail,
        success=success,
    )
    preview = build_delegate_preview(detail)
    _update_or_write_delegate_card(orch, card, resolved_task, success, preview)
