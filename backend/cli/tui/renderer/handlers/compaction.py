"""Compaction / condensation event handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.ledger.action.agent import CondensationAction
from backend.ledger.observation import AgentCondensationObservation

if TYPE_CHECKING:
    from backend.cli.tui.renderer.mixins.event_processor import (
        RendererEventProcessorMixin,
    )


def _is_noop_condensation_action(action: CondensationAction) -> bool:
    if action.summary is not None:
        return False
    return len(action.pruned or []) == 0


def _condensation_summary_text(action: CondensationAction) -> str:
    summary = (action.summary or '').strip()
    if summary:
        return summary
    pruned = len(action.pruned or [])
    if pruned:
        return f'Context condensed ({pruned} events pruned).'
    return 'Context condensed.'


def _finish_compaction_card(
    orch: 'RendererEventProcessorMixin', *, summary: str
) -> None:
    orch._compaction_transcript_active = False
    count = max(orch._condensation_count, 1)
    orch._condensation_count = count
    orch._hud.update_condensation_count(count)
    orch._complete_compaction_scan_card(summary=summary)


def show_compaction_started_card(orch: 'RendererEventProcessorMixin') -> None:
    """Ensure an in-progress compaction is visible in the transcript."""
    already_active = getattr(orch, '_compaction_transcript_active', False)
    if already_active:
        return
    count = max(orch._condensation_count + 1, 1)
    orch._condensation_count = count
    orch._compaction_transcript_active = True
    orch._create_compaction_scan_card()
    orch._hud.update_condensation_count(count)


def _handle_agent_condensation_observation(
    orch: 'RendererEventProcessorMixin', event: AgentCondensationObservation
) -> None:
    summary = (event.content or '').strip()
    _finish_compaction_card(orch, summary=summary)


def _handle_condensation_action(
    orch: 'RendererEventProcessorMixin', event: CondensationAction
) -> None:
    """Complete the compaction card when condensation commits.

    Production runs emit ``CondensationAction`` to the event stream with the
    LLM/session summary attached. ``AgentCondensationObservation`` is synthesized
    only for prompt replay (``View.from_events``) and does not reach the TUI.
    """
    if _is_noop_condensation_action(event):
        _finish_compaction_card(orch, summary='Context condensed.')
        return

    summary = _condensation_summary_text(event)
    _finish_compaction_card(orch, summary=summary)


def _handle_compaction_trigger(orch: 'RendererEventProcessorMixin', event: Any) -> None:
    del event
    show_compaction_started_card(orch)
