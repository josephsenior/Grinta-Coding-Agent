"""Unit tests for backend.controller.safety_validator — production safety layer."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.controller.safety_validator import (
    ExecutionContext,
    SafetyValidator,
    ValidationResult,
)
from backend.events.action import ActionSecurityRisk
from backend.security.command_analyzer import RiskCategory
from backend.security.safety_config import SafetyConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**overrides) -> SafetyConfig:
    defaults = dict(
        blocked_patterns=[],
        allowed_exceptions=[],
        risk_threshold="HIGH",
        enable_audit_logging=False,
        environment="production",
        enable_mandatory_validation=True,
        block_in_production=True,
        require_review_for_high_risk=False,
        enable_risk_alerts=False,
    )
    defaults.update(overrides)
    return SafetyConfig(**defaults)


def _make_context(**overrides) -> ExecutionContext:
    defaults = dict(
        session_id="test-session",
        iteration=1,
        agent_state="running",
        recent_errors=[],
        is_autonomous=True,
    )
    defaults.update(overrides)
    return ExecutionContext(**defaults)


def _make_action(command: str = "echo hello"):
    action = MagicMock()
    action.command = command
    type(action).__name__ = "CmdRunAction"
    return action


# ---------------------------------------------------------------------------
# ExecutionContext dataclass
# ---------------------------------------------------------------------------


class TestExecutionContext:
    def test_fields(self):
        ctx = ExecutionContext(
            session_id="s1",
            iteration=5,
            agent_state="running",
            recent_errors=["err1"],
            is_autonomous=False,
        )
        assert ctx.session_id == "s1"
        assert ctx.iteration == 5
        assert ctx.is_autonomous is False
        assert ctx.recent_errors == ["err1"]


# ---------------------------------------------------------------------------
# ValidationResult dataclass
# ---------------------------------------------------------------------------


class TestValidationResult:
    def test_allowed_result(self):
        r = ValidationResult(
            allowed=True,
            risk_level=ActionSecurityRisk.LOW,
            risk_category=RiskCategory.NONE,
            reason="safe",
            matched_patterns=[],
        )
        assert r.allowed is True
        assert r.requires_review is False
        assert r.audit_id is None

    def test_blocked_result(self):
        r = ValidationResult(
            allowed=False,
            risk_level=ActionSecurityRisk.HIGH,
            risk_category=RiskCategory.CRITICAL,
            reason="dangerous",
            matched_patterns=["rm -rf /"],
            blocked_reason="CRITICAL RISK",
        )
        assert r.allowed is False
        assert r.blocked_reason == "CRITICAL RISK"


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestInit:
    def test_basic_init(self):
        cfg = _make_config()
        sv = SafetyValidator(cfg)
        assert sv.config is cfg
        assert sv.analyzer is not None
        assert sv.telemetry_logger is None

    def test_init_passes_config_to_analyzer(self):
        cfg = _make_config(blocked_patterns=["rm -rf"])
        sv = SafetyValidator(cfg)
        assert sv.analyzer is not None


# ---------------------------------------------------------------------------
# _should_block_action
# ---------------------------------------------------------------------------


class TestShouldBlockAction:
    def test_critical_always_blocked(self):
        cfg = _make_config()
        sv = SafetyValidator(cfg)
        assessment = MagicMock()
        assessment.risk_category = RiskCategory.CRITICAL
        ctx = _make_context()
        assert sv._should_block_action(assessment, ctx) is True

    def test_low_risk_allowed(self):
        cfg = _make_config()
        sv = SafetyValidator(cfg)
        assessment = MagicMock()
        assessment.risk_category = RiskCategory.NONE
        assessment.risk_level = ActionSecurityRisk.LOW
        ctx = _make_context()
        assert sv._should_block_action(assessment, ctx) is False


# ---------------------------------------------------------------------------
# _requires_human_review
# ---------------------------------------------------------------------------


class TestRequiresHumanReview:
    def test_disabled_returns_false(self):
        cfg = _make_config(require_review_for_high_risk=False)
        sv = SafetyValidator(cfg)
        assessment = MagicMock()
        assessment.risk_level = ActionSecurityRisk.HIGH
        assert sv._requires_human_review(assessment) is False

    def test_enabled_high_risk_returns_true(self):
        cfg = _make_config(require_review_for_high_risk=True)
        sv = SafetyValidator(cfg)
        assessment = MagicMock()
        assessment.risk_level = ActionSecurityRisk.HIGH
        assert sv._requires_human_review(assessment) is True


# ---------------------------------------------------------------------------
# _get_blocked_reason
# ---------------------------------------------------------------------------


class TestGetBlockedReason:
    def test_critical_reason(self):
        cfg = _make_config()
        sv = SafetyValidator(cfg)
        assessment = MagicMock()
        assessment.risk_category = RiskCategory.CRITICAL
        assessment.reason = "dangerous command"
        assessment.matched_patterns = ["rm -rf /"]
        reason = sv._get_blocked_reason(assessment)
        assert "CRITICAL" in reason
        assert "rm -rf /" in reason

    def test_high_risk_reason(self):
        cfg = _make_config(environment="production")
        sv = SafetyValidator(cfg)
        assessment = MagicMock()
        assessment.risk_category = RiskCategory.HIGH
        assessment.risk_level = ActionSecurityRisk.HIGH
        assessment.reason = "risky"
        assessment.matched_patterns = ["sudo"]
        reason = sv._get_blocked_reason(assessment)
        assert "HIGH RISK" in reason
        assert "production" in reason


# ---------------------------------------------------------------------------
# _format_alert_message
# ---------------------------------------------------------------------------


class TestFormatAlertMessage:
    def test_blocked_format(self):
        cfg = _make_config()
        sv = SafetyValidator(cfg)
        action = _make_action("rm -rf /")
        ctx = _make_context()
        result = ValidationResult(
            allowed=False,
            risk_level=ActionSecurityRisk.HIGH,
            risk_category=RiskCategory.CRITICAL,
            reason="critical command",
            matched_patterns=[],
        )
        msg = sv._format_alert_message(action, ctx, result)
        assert "BLOCKED" in msg
        assert "test-session" in msg

    def test_allowed_high_risk_format(self):
        cfg = _make_config()
        sv = SafetyValidator(cfg)
        action = _make_action()
        ctx = _make_context()
        result = ValidationResult(
            allowed=True,
            risk_level=ActionSecurityRisk.HIGH,
            risk_category=RiskCategory.HIGH,
            reason="high risk",
            matched_patterns=[],
        )
        msg = sv._format_alert_message(action, ctx, result)
        assert "HIGH RISK" in msg


# ---------------------------------------------------------------------------
# validate (async integration)
# ---------------------------------------------------------------------------


class TestValidate:
    @pytest.mark.asyncio
    async def test_safe_command_allowed(self):
        cfg = _make_config()
        sv = SafetyValidator(cfg)
        action = _make_action("echo hello")
        ctx = _make_context()
        result = await sv.validate(action, ctx)
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_action_without_command_attr(self):
        """Actions without .command use str() fallback."""
        cfg = _make_config()
        sv = SafetyValidator(cfg)

        class FakeAction:
            """Action without .command attribute."""

            def __str__(self):
                return "some action string"

        action = FakeAction()
        ctx = _make_context()
        result = await sv.validate(action, ctx)
        assert isinstance(result, ValidationResult)
