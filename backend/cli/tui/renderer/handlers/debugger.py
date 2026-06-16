"""Debugger event handlers for the TUI renderer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.ledger.action import DebuggerAction
from backend.ledger.observation import DebuggerObservation

if TYPE_CHECKING:
    from backend.cli.tui.renderer.mixins.event_processor import (
        RendererEventProcessorMixin,
    )


def _handle_debugger_action(
    orch: 'RendererEventProcessorMixin', event: DebuggerAction
) -> None:
    orch._handle_debugger_action_card(event)


def _handle_debugger_observation(
    orch: 'RendererEventProcessorMixin', event: DebuggerObservation
) -> None:
    orch._handle_debugger_observation_card(event)
