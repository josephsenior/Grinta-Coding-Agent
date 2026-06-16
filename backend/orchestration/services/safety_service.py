from __future__ import annotations

from typing import TYPE_CHECKING

from backend.core.logger import app_logger as logger
from backend.ledger import EventSource
from backend.ledger.action import (
    Action,
    ActionConfirmationStatus,
    ActionSecurityRisk,
    BlackboardAction,
    BrowseInteractiveAction,
    BrowserToolAction,
    CmdRunAction,
    DelegateTaskAction,
    FileEditAction,
    FileWriteAction,
    MCPAction,
    TerminalInputAction,
    TerminalRunAction,
)

if TYPE_CHECKING:
    from backend.orchestration.services.orchestration_context import (
        OrchestrationContext,
    )


def _autonomy_level(autonomy: object | None) -> str:
    if autonomy is None:
        return ''
    from backend.orchestration.autonomy import normalize_autonomy_level

    return normalize_autonomy_level(getattr(autonomy, 'autonomy_level', ''))


class SafetyService:
    """Manages security analysis and confirmation workflow for actions."""

    _CONFIRMATION_TYPES = (
        CmdRunAction,
        BrowseInteractiveAction,
        BrowserToolAction,
        FileEditAction,
        FileWriteAction,
        TerminalRunAction,
        TerminalInputAction,
        MCPAction,
        DelegateTaskAction,
        BlackboardAction,
    )

    def __init__(self, context: OrchestrationContext) -> None:
        self._context = context

    def action_requires_confirmation(self, action: Action) -> bool:
        """Return True when action type is subject to confirmation flow."""
        return isinstance(action, self._CONFIRMATION_TYPES)

    def confirmation_disabled_by_autonomy(self) -> bool:
        """True when the configured autonomy level forbids confirmation prompts."""
        from backend.orchestration.autonomy import AutonomyLevel

        return (
            _autonomy_level(self._context.autonomy_controller)
            == AutonomyLevel.FULL.value
        )

    def evaluate_security_risk(self, action: Action) -> tuple[bool, bool]:
        """Return (is_high_risk, ask_for_every_action) tuple."""
        security_risk = getattr(action, 'security_risk', ActionSecurityRisk.UNKNOWN)
        if not isinstance(security_risk, ActionSecurityRisk):
            security_risk = ActionSecurityRisk.UNKNOWN
        analyzer = self._context.security_analyzer
        is_high_security_risk = security_risk >= ActionSecurityRisk.HIGH
        is_ask_for_every_action = security_risk == ActionSecurityRisk.UNKNOWN and (
            analyzer is None
        )
        return (is_high_security_risk, is_ask_for_every_action)

    async def analyze_security(self, action: Action) -> None:
        """Invoke configured security analyzer, falling back to UNKNOWN risk."""
        analyzer = self._context.security_analyzer
        if not analyzer:
            return

        try:
            declared = getattr(action, 'security_risk', ActionSecurityRisk.UNKNOWN)
            if not isinstance(declared, ActionSecurityRisk):
                declared = ActionSecurityRisk.UNKNOWN
            if hasattr(action, 'security_risk') and action.security_risk is not None:
                logger.debug(
                    'Original security risk for %s: %s', action, action.security_risk
                )
            if hasattr(action, 'security_risk'):
                analyzed = await analyzer.security_risk(action)
                action.security_risk = max(declared, analyzed)
                logger.debug(
                    '[Security Analyzer: %s] Effective security risk for action %s: %s',
                    analyzer.__class__,
                    action,
                    action.security_risk,
                )
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning(
                'Failed to analyze security risk for action %s: %s', action, exc
            )
            if hasattr(action, 'security_risk'):
                action.security_risk = ActionSecurityRisk.UNKNOWN

    def apply_confirmation_state(
        self,
        action: Action,
        *,
        is_high_security_risk: bool,
        is_ask_for_every_action: bool,
    ) -> None:
        """Decide whether to mark the action as awaiting confirmation."""
        autonomy = self._context.autonomy_controller
        self._context.get_controller()

        if self.confirmation_disabled_by_autonomy():
            if hasattr(action, 'confirmation_state'):
                action.confirmation_state = ActionConfirmationStatus.CONFIRMED
            logger.debug(
                '[Full autonomy] Executing action without confirmation: %s',
                type(action).__name__,
            )
            return

        if is_high_security_risk:
            action.confirmation_state = ActionConfirmationStatus.AWAITING_CONFIRMATION
        elif autonomy and autonomy.should_request_confirmation(action):
            action.confirmation_state = ActionConfirmationStatus.AWAITING_CONFIRMATION
        else:
            logger.debug(
                '[Autonomous mode] Executing action without confirmation: %s',
                type(action).__name__,
            )

    def finalize_pending_action(self, confirmed: bool) -> None:
        """Emit the pending action after confirmation or rejection."""
        pending_action = self._context.pending_action
        if pending_action is None:
            return

        if hasattr(pending_action, 'thought'):
            pending_action.thought = ''

        pending_action.confirmation_state = (
            ActionConfirmationStatus.CONFIRMED
            if confirmed
            else ActionConfirmationStatus.REJECTED
        )
        pending_action._id = None  # allow event re-emission
        self._context.clear_pending_action()
        self._context.emit_event(pending_action, EventSource.AGENT)
