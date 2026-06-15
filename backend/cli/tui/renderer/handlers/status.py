"""Status strip, error/success, and retry observation handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.cli.event_rendering.error_panel import notice_panel_title
from backend.cli.tui.renderer.handlers.compaction import show_compaction_started_card
from backend.cli.tui.renderer.helpers.status import TRANSIENT_HUD_ONLY_CATEGORIES
from backend.ledger.observation import (
    ErrorObservation,
    StatusObservation,
    SuccessObservation,
)

if TYPE_CHECKING:
    from backend.cli.tui.renderer.mixins.event_processor import (
        RendererEventProcessorMixin,
    )


def _handle_error_observation(
    orch: 'RendererEventProcessorMixin', event: ErrorObservation
) -> None:
    orch._compaction_transcript_active = False
    content = event.content or 'An unknown error occurred'
    if getattr(event, 'notify_ui_only', False):
        error_category = getattr(event, 'error_category', None)
        if error_category and error_category not in TRANSIENT_HUD_ONLY_CATEGORIES:
            summary = notice_panel_title(content, error_category=error_category)
            first_line = content.split('\n', 1)[0].strip()
            orch._update_runtime_strip(summary, first_line, active=True)
        return
    orch._tui.add_warning(content)


def _handle_success_observation(
    orch: 'RendererEventProcessorMixin', event: SuccessObservation
) -> None:
    orch._compaction_transcript_active = False
    orch._clear_retry_strip('Recovered')
    orch._clear_runtime_strip('Recovered')
    orch._tui.add_success(event.content or 'Done')


def _handle_status_retry(
    orch: 'RendererEventProcessorMixin',
    status_type: str,
    extras: dict,
) -> None:
    label, last_status, message = orch._format_retry_status_message(status_type, extras)
    orch._hud.update_ledger('Backoff')
    orch._hud.update_agent_state(label)
    orch._tui.set_agent_phase(label)
    orch._update_retry_strip(label, message)


def _handle_status_compaction(
    orch: 'RendererEventProcessorMixin',
) -> None:
    orch._clear_retry_strip('Idle')
    orch._hud.update_agent_state('Compacting')
    orch._tui.set_agent_phase('Compacting context...')
    orch._update_runtime_strip(
        'Compacting context',
        'Reducing context to continue the task',
        active=True,
    )
    show_compaction_started_card(orch)


def _handle_status_notice(
    orch: 'RendererEventProcessorMixin',
    event: StatusObservation,
    status_type: str,
) -> None:
    msg = (event.content or '').strip()
    if not msg:
        return
    summary = (
        status_type.replace('_', ' ').strip().title()
        if status_type
        else 'Runtime notice'
    )
    orch._update_runtime_strip(summary, msg, active=False)


def _handle_status_observation(
    orch: 'RendererEventProcessorMixin', event: StatusObservation
) -> None:
    status_type = str(getattr(event, 'status_type', '') or '')
    extras = getattr(event, 'extras', None) or {}
    if status_type in (
        'retry_pending',
        'retry_resuming',
        'llm_retry_pending',
        'llm_retry_resuming',
    ):
        _handle_status_retry(orch, status_type, extras)
        return
    if status_type == 'compaction':
        _handle_status_compaction(orch)
        return
    _handle_status_notice(orch, event, status_type)
