"""Production safety validator for autonomous agent actions.

This validator provides a mandatory safety layer that works even in full autonomy mode,
preventing dangerous operations while logging all actions for audit trails.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.security.safety_config import SafetyConfig

from backend.core.logger import FORGE_logger as logger
from backend.events.action import Action, ActionSecurityRisk
from backend.security.command_analyzer import CommandAnalyzer, RiskCategory


@dataclass
class ExecutionContext:
    """Context for action execution."""

    session_id: str
    iteration: int
    agent_state: str
    recent_errors: list[str]
    is_autonomous: bool


@dataclass
class ValidationResult:
    """Result of safety validation."""

    allowed: bool
    risk_level: ActionSecurityRisk
    risk_category: RiskCategory
    reason: str
    matched_patterns: list[str]
    requires_review: bool = False
    audit_id: str | None = None
    blocked_reason: str | None = None


class SafetyValidator:
    """Validates actions for safety in production environments.

    This validator works as a mandatory safety layer even when the agent
    is in full autonomy mode. It:
    - Blocks critical/high-risk commands in production
    - Logs all actions to audit trail
    - Optionally queues high-risk actions for human review
    - Sends alerts for suspicious activity
    """

    def __init__(self, config: SafetyConfig) -> None:
        """Initialize the safety validator.

        Args:
            config: Safety configuration

        """
        self.config = config
        self.analyzer = CommandAnalyzer(
            {
                "blocked_commands": config.blocked_patterns,
                "allowed_commands": config.allowed_exceptions,
                "risk_threshold": config.risk_threshold,
            },
        )

        # Import audit logger if enabled
        self.telemetry_logger = None
        if config.enable_audit_logging:
            try:
                from backend.telemetry.telemetry_logger import AuditLogger

                self.telemetry_logger = AuditLogger(config.audit_log_path)
            except ImportError:
                logger.warning("AuditLogger not available, audit logging disabled")

        logger.info(
            "SafetyValidator initialized: environment=%s, "
            "risk_threshold=%s, "
            "mandatory_validation=%s",
            config.environment,
            config.risk_threshold,
            config.enable_mandatory_validation,
        )

    async def validate(
        self, action: Action, context: ExecutionContext
    ) -> ValidationResult:
        """Validate an action for safety.

        This is the main entry point for safety validation. It analyzes the action,
        determines if it should be allowed, and logs to audit trail.

        Args:
            action: The action to validate
            context: Execution context information

        Returns:
            ValidationResult indicating if action is allowed

        """
        # Analyze the action
        # CommandAnalyzer.analyze takes a command string, not an action
        command = action.command if hasattr(action, "command") else str(action)
        raw_assessment = self.analyzer.analyze(command)

        # raw_assessment is a tuple: (RiskCategory, str, list[str])
        risk_category, reason, matched_patterns = raw_assessment
        # Convert RiskCategory to ActionSecurityRisk

        risk_level_map = {
            "none": ActionSecurityRisk.LOW,
            "low": ActionSecurityRisk.LOW,
            "medium": ActionSecurityRisk.MEDIUM,
            "high": ActionSecurityRisk.HIGH,
            "critical": ActionSecurityRisk.HIGH,
        }
        risk_level = risk_level_map.get(
            risk_category.value.lower(), ActionSecurityRisk.UNKNOWN
        )

        # Build a structured assessment for downstream helpers
        from types import SimpleNamespace

        assessment = SimpleNamespace(
            risk_category=risk_category,
            reason=reason,
            matched_patterns=matched_patterns,
            risk_level=risk_level,
        )

        # Determine if action should be blocked
        should_block = self._should_block_action(assessment, context)

        # Create validation result
        result = ValidationResult(
            allowed=not should_block,
            risk_level=risk_level,
            risk_category=risk_category,
            reason=reason,
            matched_patterns=matched_patterns,
            requires_review=self._requires_human_review(assessment),
            blocked_reason=self._get_blocked_reason(assessment)
            if should_block
            else None,
        )

        # Log to audit trail
        if self.telemetry_logger:
            result.audit_id = await self._log_to_audit(action, context, result)

        # Send alerts if needed
        if should_block or result.risk_level == ActionSecurityRisk.HIGH:
            await self._send_alert(action, context, result)

        return result

    def _should_block_action(self, assessment, context: ExecutionContext) -> bool:
        """Determine if an action should be blocked.

        Args:
            assessment: CommandRiskAssessment from analyzer
            context: Execution context

        Returns:
            True if action should be blocked

        """
        # Always block CRITICAL risks
        if assessment.risk_category == RiskCategory.CRITICAL:
            logger.error(
                "CRITICAL risk action blocked: %s (session=%s, iteration=%s)",
                assessment.reason,
                context.session_id,
                context.iteration,
            )
            return True

        # Block HIGH risks in production
        if (
            assessment.risk_level == ActionSecurityRisk.HIGH
            and self.config.environment == "production"
            and self.config.block_in_production
        ):
            logger.warning(
                "HIGH risk action blocked in production: %s (session=%s)",
                assessment.reason,
                context.session_id,
            )
            return True

        # Block HIGH risks if not using mandatory validation and in autonomous mode
        if (
            assessment.risk_level == ActionSecurityRisk.HIGH
            and self.config.enable_mandatory_validation
            and context.is_autonomous
            and self.config.risk_threshold in ["critical", "high"]
        ):
            logger.warning(
                "HIGH risk action blocked in autonomous mode: %s",
                assessment.reason,
            )
            return True

        return False

    def _requires_human_review(self, assessment) -> bool:
        """Check if action requires human review.

        Args:
            assessment: CommandRiskAssessment from analyzer

        Returns:
            True if human review required

        """
        if not self.config.require_review_for_high_risk:
            return False

        return assessment.risk_level == ActionSecurityRisk.HIGH

    def _get_blocked_reason(self, assessment) -> str:
        """Get human-readable reason for blocking.

        Args:
            assessment: CommandRiskAssessment from analyzer

        Returns:
            Blocked reason string

        """
        if assessment.risk_category == RiskCategory.CRITICAL:
            return (
                f"CRITICAL RISK DETECTED: {assessment.reason}\n"
                f"This action could cause system damage or data loss.\n"
                f"Matched patterns: {', '.join(assessment.matched_patterns)}"
            )
        if assessment.risk_level == ActionSecurityRisk.HIGH:
            return (
                f"HIGH RISK DETECTED: {assessment.reason}\n"
                f"This action is blocked in {self.config.environment} environment.\n"
                f"Matched patterns: {', '.join(assessment.matched_patterns)}"
            )
        return assessment.reason

    async def _log_to_audit(
        self,
        action: Action,
        context: ExecutionContext,
        result: ValidationResult,
    ) -> str:
        """Log action to audit trail.

        Args:
            action: The action being validated
            context: Execution context
            result: Validation result

        Returns:
            Audit entry ID

        """
        if not self.telemetry_logger:
            return "audit_disabled"

        try:
            return await self.telemetry_logger.log_action(
                session_id=context.session_id,
                iteration=context.iteration,
                action=action,
                validation_result=result,
                timestamp=datetime.now(),
            )
        except Exception as e:
            logger.error("Failed to log to audit trail: %s", e)
            return "audit_error"

    async def _send_alert(
        self,
        action: Action,
        context: ExecutionContext,
        result: ValidationResult,
    ) -> None:
        """Send alert for high-risk or blocked action.

        Args:
            action: The action being validated
            context: Execution context
            result: Validation result

        """
        if not self.config.enable_risk_alerts:
            return

        alert_message = self._format_alert_message(action, context, result)
        logger.warning("SECURITY ALERT: %s", alert_message)

        # Send webhook alert if configured
        if self.config.alert_webhook_url:
            from backend.utils.async_utils import create_tracked_task

            create_tracked_task(
                self._send_webhook_alert(alert_message),
                name="safety-webhook-alert",
            )

    def _format_alert_message(
        self,
        action: Action,
        context: ExecutionContext,
        result: ValidationResult,
    ) -> str:
        """Format alert message.

        Args:
            action: The action
            context: Execution context
            result: Validation result

        Returns:
            Formatted alert message

        """
        status = "BLOCKED" if not result.allowed else "HIGH RISK"
        return (
            f"{status}: {result.reason}\n"
            f"Session: {context.session_id}\n"
            f"Iteration: {context.iteration}\n"
            f"Action: {type(action).__name__}\n"
            f"Risk Level: {result.risk_level.name}\n"
            f"Environment: {self.config.environment}"
        )

    async def _send_webhook_alert(self, message: str) -> None:
        """Send alert to webhook (Slack/Discord).

        Args:
            message: Alert message to send

        """
        url = getattr(self.config, "alert_webhook_url", None)
        if not url:
            logger.debug("No alert webhook URL configured; skipping webhook alert.")
            return

        try:
            import aiohttp

            async with aiohttp.ClientSession() as session:
                payload = {"text": message, "username": "Forge Security"}
                async with session.post(
                    url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as response:
                    if response.status != 200:
                        logger.error(
                            "Failed to send webhook alert: %s", response.status
                        )
        except Exception as e:
            logger.error("Error sending webhook alert: %s", e)
