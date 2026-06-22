"""SafetyService unknown-risk confirmation behavior."""

from __future__ import annotations

from unittest.mock import MagicMock

from backend.ledger.action import ActionConfirmationStatus, ActionSecurityRisk
from backend.ledger.action.commands import CmdRunAction
from backend.orchestration.services.safety_service import SafetyService


def test_unknown_risk_without_analyzer_prompts() -> None:
    context = MagicMock()
    context.autonomy_controller = MagicMock()
    context.autonomy_controller.should_request_confirmation.return_value = False
    context.get_controller.return_value = MagicMock()
    service = SafetyService(context)
    service._context.security_analyzer = None

    action = CmdRunAction(command='echo hi')
    action.security_risk = ActionSecurityRisk.UNKNOWN
    is_high, ask_every = service.evaluate_security_risk(action)
    assert ask_every is True

    service.apply_confirmation_state(
        action,
        is_high_security_risk=is_high,
        is_ask_for_every_action=ask_every,
    )
    assert action.confirmation_state == ActionConfirmationStatus.AWAITING_CONFIRMATION
