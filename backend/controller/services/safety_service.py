from __future__ import annotations

from typing import TYPE_CHECKING

from backend.core.logger import forge_logger as logger
from backend.events import EventSource
from backend.events.action import (
    Action,
    ActionConfirmationStatus,
    ActionSecurityRisk,
    CmdRunAction,
    FileEditAction,
    FileReadAction,
)

if TYPE_CHECKING:
    from backend.controller.services.controller_context import ControllerContext


class SafetyService:
    """Manages security analysis and confirmation workflow for actions."""

    _CONFIRMATION_TYPES = (
        CmdRunAction,
        FileEditAction,
        FileReadAction,
    )

    def __init__(self, context: ControllerContext) -> None:
        self._context = context

    def action_requires_confirmation(self, action: Action) -> bool:
        """Return True when action type is subject to confirmation flow."""
        return isinstance(action, self._CONFIRMATION_TYPES)

    def evaluate_security_risk(self, action: Action) -> tuple[bool, bool]:
        """Return (is_high_risk, ask_for_every_action) tuple."""
        security_risk = getattr(action, "security_risk", ActionSecurityRisk.UNKNOWN)
        analyzer = self._context.security_analyzer
        is_high_security_risk = security_risk == ActionSecurityRisk.HIGH
        is_ask_for_every_action = security_risk == ActionSecurityRisk.UNKNOWN and (
            analyzer is None
        )
        return (is_high_security_risk, is_ask_for_every_action)

    async def analyze_security(self, action: Action) -> None:
        """Invoke configured security analyzer, falling back to UNKNOWN risk."""
        analyzer = self._context.security_analyzer
        if not analyzer:
            if hasattr(action, "security_risk"):
                action.security_risk = ActionSecurityRisk.UNKNOWN
            return

        try:
            if hasattr(action, "security_risk") and action.security_risk is not None:
                logger.debug(
                    "Original security risk for %s: %s", action, action.security_risk
                )
            if hasattr(action, "security_risk"):
                action.security_risk = await analyzer.security_risk(action)
                logger.debug(
                    "[Security Analyzer: %s] Override security risk for action %s: %s",
                    analyzer.__class__,
                    action,
                    action.security_risk,
                )
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning(
                "Failed to analyze security risk for action %s: %s", action, exc
            )
            if hasattr(action, "security_risk"):
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
        controller = self._context.get_controller()

        if autonomy and autonomy.should_request_confirmation(action):
            if controller.agent.config.cli_mode:
                action.confirmation_state = (
                    ActionConfirmationStatus.AWAITING_CONFIRMATION
                )
            elif self._context.confirmation_mode and (
                is_high_security_risk or is_ask_for_every_action
            ):
                logger.debug(
                    "[non-CLI mode] Detected HIGH security risk in action: %s. Ask for confirmation",
                    action,
                )
                action.confirmation_state = (
                    ActionConfirmationStatus.AWAITING_CONFIRMATION
                )
        else:
            logger.debug(
                "[Autonomous mode] Executing action without confirmation: %s",
                type(action).__name__,
            )

    def finalize_pending_action(self, confirmed: bool) -> None:
        """Emit the pending action after confirmation or rejection."""
        pending_action = self._context.pending_action
        if pending_action is None:
            return

        if hasattr(pending_action, "thought"):
            pending_action.thought = ""

        pending_action.confirmation_state = (
            ActionConfirmationStatus.CONFIRMED
            if confirmed
            else ActionConfirmationStatus.REJECTED
        )
        pending_action._id = None  # allow event re-emission
        self._context.emit_event(pending_action, EventSource.AGENT)
        self._context.clear_pending_action()
