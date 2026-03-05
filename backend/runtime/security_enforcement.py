"""Security enforcement mixin for Runtime action gating.

Extracts security risk evaluation and action confirmation checks from
the Runtime base class into a focused, testable mixin.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.core.logger import forge_logger as logger

if TYPE_CHECKING:
    from backend.events.action import Action
    from backend.events.observation import Observation


class SecurityEnforcementMixin:
    """Mixin that gates action execution based on security risk assessment.

    Expects the host class to provide:
        - ``self.security_analyzer: SecurityAnalyzer | None``
        - ``self.config.security`` with ``enforce_security`` and ``block_high_risk``
    """

    security_analyzer: Any
    config: Any

    def _check_action_confirmation(self, action: Action) -> Observation | None:
        """Check action confirmation state and return appropriate observation."""
        from backend.events.action import (
            ActionConfirmationStatus,
            FileEditAction,
        )
        from backend.events.observation import NullObservation, UserRejectObservation

        if (
            hasattr(action, "confirmation_state")
            and action.confirmation_state
            == ActionConfirmationStatus.AWAITING_CONFIRMATION
        ):
            # Allow file edits to run in runtime preview mode (dry-run) so users can
            # review diffs before confirming. Other actions remain blocked.
            if isinstance(action, FileEditAction):
                return None
            return NullObservation("")

        if (
            getattr(action, "confirmation_state", None)
            == ActionConfirmationStatus.REJECTED
        ):
            return UserRejectObservation(
                "Action has been rejected by the user! Waiting for further user input."
            )

        return None

    def _enforce_security(self, action: Action) -> Observation | None:
        """Evaluate action risk via SecurityAnalyzer and enforce policy.

        Returns:
            * ``None`` — action may proceed.
            * ``ErrorObservation`` — action is blocked (HIGH risk + ``block_high_risk``).
            * ``NullObservation`` — action needs user confirmation (HIGH risk, not blocking).
        """
        from backend.core.enums import ActionSecurityRisk
        from backend.events.action import ActionConfirmationStatus
        from backend.events.observation import ErrorObservation, NullObservation

        if self.security_analyzer is None:  # type: ignore[attr-defined]
            return None

        sec_cfg = self.config.security  # type: ignore[attr-defined]
        if not sec_cfg.enforce_security:
            return None

        import asyncio

        risk: Any
        try:
            risk = asyncio.run(self.security_analyzer.security_risk(action))
        except Exception:
            logger.warning(
                "Security analysis failed for %s, allowing action to proceed",
                action.action,
                exc_info=True,
            )
            return None

        if risk >= ActionSecurityRisk.HIGH:
            action_desc = f"{action.action}: {str(action)[:120]}"
            if sec_cfg.block_high_risk:
                logger.warning(
                    "Security BLOCKED high-risk action: %s (risk=%s)",
                    action_desc,
                    risk.name,
                )
                return ErrorObservation(
                    f"Action blocked by security policy (risk={risk.name}). Action: {action_desc}"
                )
            # Require user confirmation for HIGH-risk actions
            if (
                hasattr(action, "confirmation_state")
                and action.confirmation_state != ActionConfirmationStatus.CONFIRMED
            ):
                logger.info(
                    "Security: requiring confirmation for high-risk action: %s",
                    action_desc,
                )
                action.confirmation_state = (
                    ActionConfirmationStatus.AWAITING_CONFIRMATION
                )  # type: ignore[union-attr]
                return NullObservation("")

        elif risk >= ActionSecurityRisk.MEDIUM:
            logger.info(
                "Security: medium-risk action allowed: %s (risk=%s)",
                action.action,
                risk.name,
            )

        return None
