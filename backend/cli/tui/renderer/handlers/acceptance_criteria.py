"""Acceptance criteria action/observation handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.cli.tool_display.orient_tools import (
    OrientLineModel,
    acceptance_criteria_action_model,
    acceptance_criteria_observation_model,
)

if TYPE_CHECKING:
    from backend.cli.tui.renderer.mixins.event_processor import (
        RendererEventProcessorMixin,
    )

from backend.ledger.action import AcceptanceCriteriaAction
from backend.ledger.observation.acceptance_criteria import AcceptanceCriteriaObservation


def _handle_acceptance_criteria_observation(
    orch: 'RendererEventProcessorMixin', event: AcceptanceCriteriaObservation
) -> None:
    pending = getattr(orch, '_pending_acceptance_criteria_line', None)
    if isinstance(pending, OrientLineModel):
        orch._write_orient_line(acceptance_criteria_observation_model(event, pending))
    else:
        orch._write_orient_line(acceptance_criteria_observation_model(event))
    orch._pending_acceptance_criteria_line = None


def _handle_acceptance_criteria_action(
    orch: 'RendererEventProcessorMixin', event: AcceptanceCriteriaAction
) -> None:
    orch._pending_acceptance_criteria_line = acceptance_criteria_action_model(event)
