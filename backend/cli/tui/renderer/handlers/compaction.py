"""Compaction / condensation event handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.cli.event_rendering.unified_renderer import ActivityRenderer
from backend.cli.tool_display.orient_tools import OrientLineModel
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
    suffix = 'th'
    if count % 100 not in (11, 12, 13):
        suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(count % 10, 'th')
    model = OrientLineModel(
        tool='condensation',
        icon='…',
        verb=f'Compacting ({count}{suffix})',
        target='context',
        result='',
    )
    orch._write_orient_line(model)
    orch._hud.update_condensation_count(count)


def _handle_agent_condensation_observation(
    orch: 'RendererEventProcessorMixin', event: AgentCondensationObservation
) -> None:
    orch._compaction_transcript_active = False
    orch._update_runtime_strip(
        'Context compacted',
        'Context compressed successfully',
        active=False,
    )
    count = max(orch._condensation_count, 1)
    orch._condensation_count = count
    orch._hud.update_condensation_count(count)
    card = ActivityRenderer.condensation(count=count, result=event.content)
    orch._write_card(card)


def _handle_compaction_trigger(orch: 'RendererEventProcessorMixin', event: Any) -> None:
    del event
    show_compaction_started_card(orch)
