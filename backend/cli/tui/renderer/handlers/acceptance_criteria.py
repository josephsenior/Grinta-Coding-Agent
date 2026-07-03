"""Acceptance criteria action/observation handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.cli.tui.screens.detail.helpers import criteria_rows_from_observation
from backend.ledger.action import AcceptanceCriteriaAction
from backend.ledger.observation.acceptance_criteria import AcceptanceCriteriaObservation

if TYPE_CHECKING:
    from backend.cli.tui.renderer.mixins.event_processor import (
        RendererEventProcessorMixin,
    )


def _criteria_status_message(obs: AcceptanceCriteriaObservation) -> str:
    content = str(getattr(obs, 'content', '') or '').strip()
    if not content:
        return ''
    if content.startswith('[ACCEPTANCE_CRITERIA]'):
        return content.removeprefix('[ACCEPTANCE_CRITERIA]').strip(' :')
    if content.startswith('✅'):
        return content.removeprefix('✅').strip()
    return content.split('\n', 1)[0].strip()


def _criteria_success(obs: AcceptanceCriteriaObservation) -> bool:
    content = str(getattr(obs, 'content', '') or '').strip().lower()
    if not content:
        return True
    if content.startswith('[acceptance_criteria]'):
        return True
    if content.startswith('failed to read') or content.startswith('failed to write'):
        return False
    if 'no acceptance criteria found' in content:
        return True
    return not content.startswith('failed')


def _handle_acceptance_criteria_observation(
    orch: 'RendererEventProcessorMixin', event: AcceptanceCriteriaObservation
) -> None:
    from backend.cli.tui.widgets.scan_line import AcceptanceCriteriaCard

    criteria_list = criteria_rows_from_observation(event)
    status_message = _criteria_status_message(event)
    success = _criteria_success(event)
    command = str(getattr(event, 'command', '') or 'view').strip().lower()

    pending = getattr(orch, '_pending_acceptance_criteria_card', None)
    if isinstance(pending, AcceptanceCriteriaCard):
        pending.complete(
            criteria_list=criteria_list,
            status_message=status_message,
            success=success,
        )
        orch._pending_acceptance_criteria_card = None
        return

    orch._append_scan_line_card(
        AcceptanceCriteriaCard(
            command,
            criteria_list=criteria_list,
            status_message=status_message,
            success=success,
        )
    )


def _handle_acceptance_criteria_action(
    orch: 'RendererEventProcessorMixin', event: AcceptanceCriteriaAction
) -> None:
    from backend.cli.tui.widgets.scan_line import AcceptanceCriteriaCard

    command = str(getattr(event, 'command', '') or 'view').strip().lower()
    criteria_list = list(getattr(event, 'criteria_list', []) or [])
    card = AcceptanceCriteriaCard(command, criteria_list=criteria_list)
    orch._append_scan_line_card(card)
    orch._pending_acceptance_criteria_card = card
