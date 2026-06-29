"""Compaction / condensation event handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.ledger.observation import AgentCondensationObservation

if TYPE_CHECKING:
    from backend.cli.tui.renderer.mixins.event_processor import (
        RendererEventProcessorMixin,
    )


def show_compaction_started_card(orch: 'RendererEventProcessorMixin') -> None:
    """Ensure an in-progress compaction is visible in the transcript."""
    if getattr(orch, '_compaction_transcript_active', False):
        return
    count = max(orch._condensation_count + 1, 1)
    orch._condensation_count = count
    orch._compaction_transcript_active = True
    orch._create_compaction_scan_card()
    orch._hud.update_condensation_count(count)


def _handle_agent_condensation_observation(
    orch: 'RendererEventProcessorMixin', event: AgentCondensationObservation
) -> None:
    orch._compaction_transcript_active = False
    summary = (event.content or '').strip()
    count = max(orch._condensation_count, 1)
    orch._condensation_count = count
    orch._hud.update_condensation_count(count)
    orch._complete_compaction_scan_card(summary=summary)


def _handle_compaction_trigger(orch: 'RendererEventProcessorMixin', event: Any) -> None:
    del event
    show_compaction_started_card(orch)
