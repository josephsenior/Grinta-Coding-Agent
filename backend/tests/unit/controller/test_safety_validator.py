"""Tests for backend.controller.safety_validator module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.controller.safety_validator import (
    ExecutionContext,
    SafetyValidator,
    ValidationResult,
)
from backend.events.action import ActionSecurityRisk, CmdRunAction
from backend.security.command_analyzer import RiskCategory


class TestExecutionContext:
    """Tests for ExecutionContext dataclass."""

    def test_create_with_all_fields(self):
        """Test creating with all fields."""
        context = ExecutionContext(
            session_id="test_session",
            iteration=5,
            agent_state="running",
            recent_errors=[],
            is_autonomous=True,
        )
        assert context.session_id == "test_session"
        assert context.iteration == 5
        assert context.agent_state == "running"
        assert context.recent_errors == []
        assert context.is_autonomous is True

    def test_create_with_errors(self):
        """Test creating with error list."""
        errors = ["error1", "error2"]
        context = ExecutionContext(
            session_id="sess",
            iteration=1,
            agent_state="error",
            recent_errors=errors,
            is_autonomous=False,
        )
        assert context.recent_errors == errors


class TestValidationResult:
    """Tests for ValidationResult dataclass."""

    def test_create_with_required_fields(self):
        """Test creating with required fields."""
        result = ValidationResult(
            allowed=True,
            risk_level=ActionSecurityRisk.LOW,
            risk_category=RiskCategory.NONE,
            reason="safe command",
            matched_patterns=[],
        )
        assert result.allowed is True
        assert result.risk_level == ActionSecurityRisk.LOW
        assert result.risk_category == RiskCategory.NONE
        assert result.reason == "safe command"
        assert result.matched_patterns == []
        assert result.requires_review is False
        assert result.audit_id is None
        assert result.blocked_reason is None

    def test_create_with_all_fields(self):
        """Test creating with all fields."""
        result = ValidationResult(
            allowed=False,
            risk_level=ActionSecurityRisk.HIGH,
            risk_category=RiskCategory.CRITICAL,
            reason="dangerous",
            matched_patterns=["rm -rf"],
            requires_review=True,
            audit_id="audit_123",
            blocked_reason="Too dangerous",
        )
        assert result.allowed is False
        assert result.requires_review is True
        assert result.audit_id == "audit_123"
        assert result.blocked_reason == "Too dangerous"


class TestSafetyValidator:
    """Tests for SafetyValidator class."""

    def create_mock_config(self, **overrides):
        """Create a mock safety config."""
        config = MagicMock()
        config.environment = overrides.get("environment", "development")
        config.blocked_patterns = overrides.get("blocked_patterns", [])
        config.allowed_exceptions = overrides.get("allowed_exceptions", [])
        config.risk_threshold = overrides.get("risk_threshold", "high")
        config.enable_audit_logging = overrides.get("enable_audit_logging", False)
        config.audit_log_path = overrides.get("audit_log_path", "/tmp/audit.log")
        config.enable_mandatory_validation = overrides.get(
            "enable_mandatory_validation", True
        )
        config.block_in_production = overrides.get("block_in_production", True)
        config.require_review_for_high_risk = overrides.get(
            "require_review_for_high_risk", False
        )
        config.enable_risk_alerts = overrides.get("enable_risk_alerts", False)
        config.alert_webhook_url = overrides.get("alert_webhook_url")
        return config

    def test_init_creates_analyzer(self):
        """Test initialization creates CommandAnalyzer."""
        config = self.create_mock_config(
            blocked_patterns=["rm -rf"],
            allowed_exceptions=["safe.txt"],
        )

        validator = SafetyValidator(config)

        assert hasattr(validator, "analyzer")
        assert validator.config == config

    def test_init_without_audit_logging(self):
        """Test initialization without audit logging."""
        config = self.create_mock_config(enable_audit_logging=False)

        validator = SafetyValidator(config)

        assert validator.telemetry_logger is None

    @pytest.mark.asyncio
    async def test_validate_low_risk_allowed(self):
        """Test validate allows low-risk actions."""
        config = self.create_mock_config()
        validator = SafetyValidator(config)

        # Mock analyzer to return low risk
        validator.analyzer.analyze = MagicMock(
            return_value=(RiskCategory.NONE, "safe command", [])
        )

        action = CmdRunAction(command="ls")
        context = ExecutionContext(
            session_id="test",
            iteration=1,
            agent_state="running",
            recent_errors=[],
            is_autonomous=False,
        )

        result = await validator.validate(action, context)

        assert result.allowed is True
        assert result.risk_level == ActionSecurityRisk.LOW

    @pytest.mark.asyncio
    async def test_validate_critical_risk_blocked(self):
        """Test validate blocks critical risk actions."""
        config = self.create_mock_config()
        validator = SafetyValidator(config)

        # Mock analyzer to return critical risk
        validator.analyzer.analyze = MagicMock(
            return_value=(
                RiskCategory.CRITICAL,
                "dangerous command",
                ["rm -rf /"],
            )
        )

        action = CmdRunAction(command="rm -rf /")
        context = ExecutionContext(
            session_id="test",
            iteration=1,
            agent_state="running",
            recent_errors=[],
            is_autonomous=False,
        )

        result = await validator.validate(action, context)

        assert result.allowed is False
        assert result.blocked_reason is not None

    @pytest.mark.asyncio
    async def test_validate_high_risk_blocked_in_production(self):
        """Test validate blocks high-risk actions in production."""
        config = self.create_mock_config(
            environment="production",
            block_in_production=True,
        )
        validator = SafetyValidator(config)

        # Mock analyzer to return high risk
        validator.analyzer.analyze = MagicMock(
            return_value=(
                RiskCategory.HIGH,
                "risky command",
                ["sudo"],
            )
        )

        action = CmdRunAction(command="sudo reboot")
        context = ExecutionContext(
            session_id="test",
            iteration=1,
            agent_state="running",
            recent_errors=[],
            is_autonomous=False,
        )

        result = await validator.validate(action, context)

        assert result.allowed is False

    @pytest.mark.asyncio
    async def test_validate_high_risk_allowed_in_development(self):
        """Test validate allows high-risk actions in development."""
        config = self.create_mock_config(
            environment="development",
            enable_mandatory_validation=False,
        )
        validator = SafetyValidator(config)

        # Mock analyzer to return high risk
        validator.analyzer.analyze = MagicMock(
            return_value=(
                RiskCategory.HIGH,
                "risky but allowed",
                ["sudo"],
            )
        )

        action = CmdRunAction(command="sudo ls")
        context = ExecutionContext(
            session_id="test",
            iteration=1,
            agent_state="running",
            recent_errors=[],
            is_autonomous=False,
        )

        result = await validator.validate(action, context)

        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_validate_sets_requires_review_for_high_risk(self):
        """Test validate sets requires_review for high-risk actions."""
        config = self.create_mock_config(
            require_review_for_high_risk=True,
        )
        validator = SafetyValidator(config)

        # Mock analyzer to return high risk
        validator.analyzer.analyze = MagicMock(
            return_value=(
                RiskCategory.HIGH,
                "risky",
                [],
            )
        )

        action = CmdRunAction(command="test")
        context = ExecutionContext(
            session_id="test",
            iteration=1,
            agent_state="running",
            recent_errors=[],
            is_autonomous=False,
        )

        result = await validator.validate(action, context)

        assert result.requires_review is True

    @pytest.mark.asyncio
    async def test_validate_logs_to_audit_when_enabled(self):
        """Test validate calls audit logger when enabled."""
        config = self.create_mock_config(
            enable_audit_logging=False
        )  # Don't load real logger

        # Create validator and manually set audit logger
        validator = SafetyValidator(config)

        mock_logger = AsyncMock()
        mock_logger.log_action = AsyncMock(return_value="audit_xyz")
        validator.telemetry_logger = mock_logger  # Manually set

        validator.analyzer.analyze = MagicMock(
            return_value=(RiskCategory.NONE, "safe", [])
        )

        action = CmdRunAction(command="ls")
        context = ExecutionContext(
            session_id="test",
            iteration=1,
            agent_state="running",
            recent_errors=[],
            is_autonomous=False,
        )

        result = await validator.validate(action, context)

        assert result.audit_id == "audit_xyz"
        mock_logger.log_action.assert_called_once()

    @pytest.mark.asyncio
    async def test_validate_sends_alert_for_high_risk(self):
        """Test validate sends alert for high-risk actions."""
        config = self.create_mock_config(
            enable_risk_alerts=True,
        )
        validator = SafetyValidator(config)

        # Mock analyzer
        validator.analyzer.analyze = MagicMock(
            return_value=(RiskCategory.HIGH, "risky", [])
        )

        # Mock _send_alert
        validator._send_alert = AsyncMock()

        action = CmdRunAction(command="test")
        context = ExecutionContext(
            session_id="test",
            iteration=1,
            agent_state="running",
            recent_errors=[],
            is_autonomous=False,
        )

        await validator.validate(action, context)

        validator._send_alert.assert_called_once()

    def test_should_block_action_blocks_critical(self):
        """Test _should_block_action blocks CRITICAL risks."""
        config = self.create_mock_config()
        validator = SafetyValidator(config)

        # Create mock assessment
        from types import SimpleNamespace

        assessment = SimpleNamespace(
            risk_category=RiskCategory.CRITICAL,
            risk_level=ActionSecurityRisk.HIGH,
            reason="critical risk",
        )
        context = ExecutionContext(
            session_id="test",
            iteration=1,
            agent_state="running",
            recent_errors=[],
            is_autonomous=False,
        )

        should_block = validator._should_block_action(assessment, context)
        assert should_block is True

    def test_should_block_action_blocks_high_in_production(self):
        """Test _should_block_action blocks HIGH risks in production."""
        config = self.create_mock_config(
            environment="production",
            block_in_production=True,
        )
        validator = SafetyValidator(config)

        from types import SimpleNamespace

        assessment = SimpleNamespace(
            risk_category=RiskCategory.HIGH,
            risk_level=ActionSecurityRisk.HIGH,
            reason="high risk",
        )
        context = ExecutionContext(
            session_id="test",
            iteration=1,
            agent_state="running",
            recent_errors=[],
            is_autonomous=False,
        )

        should_block = validator._should_block_action(assessment, context)
        assert should_block is True

    def test_should_block_action_allows_high_in_development(self):
        """Test _should_block_action allows HIGH risks in development."""
        config = self.create_mock_config(
            environment="development",
        )
        validator = SafetyValidator(config)

        from types import SimpleNamespace

        assessment = SimpleNamespace(
            risk_category=RiskCategory.HIGH,
            risk_level=ActionSecurityRisk.HIGH,
            reason="high but dev",
        )
        context = ExecutionContext(
            session_id="test",
            iteration=1,
            agent_state="running",
            recent_errors=[],
            is_autonomous=False,
        )

        should_block = validator._should_block_action(assessment, context)
        assert should_block is False

    def test_requires_human_review_false_when_disabled(self):
        """Test _requires_human_review returns False when disabled."""
        config = self.create_mock_config(require_review_for_high_risk=False)
        validator = SafetyValidator(config)

        from types import SimpleNamespace

        assessment = SimpleNamespace(risk_level=ActionSecurityRisk.HIGH)

        requires = validator._requires_human_review(assessment)
        assert requires is False

    def test_requires_human_review_true_for_high_risk(self):
        """Test _requires_human_review returns True for HIGH risk."""
        config = self.create_mock_config(require_review_for_high_risk=True)
        validator = SafetyValidator(config)

        from types import SimpleNamespace

        assessment = SimpleNamespace(risk_level=ActionSecurityRisk.HIGH)

        requires = validator._requires_human_review(assessment)
        assert requires is True

    def test_get_blocked_reason_for_critical(self):
        """Test _get_blocked_reason for CRITICAL risk."""
        config = self.create_mock_config()
        validator = SafetyValidator(config)

        from types import SimpleNamespace

        assessment = SimpleNamespace(
            risk_category=RiskCategory.CRITICAL,
            reason="Destructive command",
            matched_patterns=["rm -rf"],
        )

        reason = validator._get_blocked_reason(assessment)
        assert "CRITICAL RISK DETECTED" in reason
        assert "Destructive command" in reason
        assert "rm -rf" in reason

    def test_get_blocked_reason_for_high(self):
        """Test _get_blocked_reason for HIGH risk."""
        config = self.create_mock_config(environment="production")
        validator = SafetyValidator(config)

        from types import SimpleNamespace

        assessment = SimpleNamespace(
            risk_category=RiskCategory.HIGH,
            risk_level=ActionSecurityRisk.HIGH,
            reason="Risky command",
            matched_patterns=["sudo"],
        )

        reason = validator._get_blocked_reason(assessment)
        assert "HIGH RISK DETECTED" in reason
        assert "production" in reason
        assert "sudo" in reason

    @pytest.mark.asyncio
    async def test_log_to_audit_returns_disabled_when_no_logger(self):
        """Test _log_to_audit returns 'audit_disabled' when no logger."""
        config = self.create_mock_config(enable_audit_logging=False)
        validator = SafetyValidator(config)

        action = CmdRunAction(command="test")
        context = ExecutionContext(
            session_id="test",
            iteration=1,
            agent_state="running",
            recent_errors=[],
            is_autonomous=False,
        )
        result = ValidationResult(
            allowed=True,
            risk_level=ActionSecurityRisk.LOW,
            risk_category=RiskCategory.NONE,
            reason="safe",
            matched_patterns=[],
        )

        audit_id = await validator._log_to_audit(action, context, result)
        assert audit_id == "audit_disabled"

    @pytest.mark.asyncio
    async def test_log_to_audit_handles_exception(self):
        """Test _log_to_audit handles exceptions."""
        config = self.create_mock_config(enable_audit_logging=False)
        validator = SafetyValidator(config)

        mock_logger = AsyncMock()
        mock_logger.log_action = AsyncMock(side_effect=Exception("test error"))
        validator.telemetry_logger = mock_logger  # Manually set

        action = CmdRunAction(command="test")
        context = ExecutionContext(
            session_id="test",
            iteration=1,
            agent_state="running",
            recent_errors=[],
            is_autonomous=False,
        )
        result = ValidationResult(
            allowed=True,
            risk_level=ActionSecurityRisk.LOW,
            risk_category=RiskCategory.NONE,
            reason="safe",
            matched_patterns=[],
        )

        audit_id = await validator._log_to_audit(action, context, result)
        assert audit_id == "audit_error"

    def test_format_alert_message_for_blocked(self):
        """Test _format_alert_message for blocked action."""
        config = self.create_mock_config(environment="production")
        validator = SafetyValidator(config)

        action = CmdRunAction(command="rm -rf /")
        context = ExecutionContext(
            session_id="sess_123",
            iteration=10,
            agent_state="running",
            recent_errors=[],
            is_autonomous=True,
        )
        result = ValidationResult(
            allowed=False,
            risk_level=ActionSecurityRisk.HIGH,
            risk_category=RiskCategory.CRITICAL,
            reason="Dangerous command",
            matched_patterns=[],
        )

        message = validator._format_alert_message(action, context, result)

        assert "BLOCKED" in message
        assert "sess_123" in message
        assert "10" in message
        assert "CmdRunAction" in message
        assert "HIGH" in message
        assert "production" in message

    def test_format_alert_message_for_high_risk(self):
        """Test _format_alert_message for allowed high-risk action."""
        config = self.create_mock_config()
        validator = SafetyValidator(config)

        action = CmdRunAction(command="test")
        context = ExecutionContext(
            session_id="test",
            iteration=1,
            agent_state="running",
            recent_errors=[],
            is_autonomous=False,
        )
        result = ValidationResult(
            allowed=True,
            risk_level=ActionSecurityRisk.HIGH,
            risk_category=RiskCategory.HIGH,
            reason="High risk but allowed",
            matched_patterns=[],
        )

        message = validator._format_alert_message(action, context, result)
        assert "HIGH RISK" in message

    @pytest.mark.asyncio
    async def test_send_alert_does_nothing_when_disabled(self):
        """Test _send_alert does nothing when alerts disabled."""
        config = self.create_mock_config(enable_risk_alerts=False)
        validator = SafetyValidator(config)

        action = CmdRunAction(command="test")
        context = ExecutionContext(
            session_id="test",
            iteration=1,
            agent_state="running",
            recent_errors=[],
            is_autonomous=False,
        )
        result = ValidationResult(
            allowed=False,
            risk_level=ActionSecurityRisk.HIGH,
            risk_category=RiskCategory.HIGH,
            reason="test",
            matched_patterns=[],
        )

        # Should not raise
        await validator._send_alert(action, context, result)

    @pytest.mark.asyncio
    async def test_send_webhook_alert_logs_no_url(self):
        """Test _send_webhook_alert logs when no URL configured."""
        config = self.create_mock_config(alert_webhook_url=None)
        validator = SafetyValidator(config)

        # Should not raise, just log
        await validator._send_webhook_alert("test message")

    @pytest.mark.asyncio
    async def test_send_webhook_alert_handles_exception(self):
        """Test _send_webhook_alert handles exceptions gracefully."""
        config = self.create_mock_config(
            alert_webhook_url="https://example.com/webhook"
        )
        validator = SafetyValidator(config)

        # Mock aiohttp to raise exception
        with patch("aiohttp.ClientSession") as mock_session:
            mock_session.return_value.__aenter__.side_effect = Exception("test error")

            # Should not raise
            await validator._send_webhook_alert("test message")
