from typing import Any, cast
"""Unit tests for backend.orchestration.tool_result_validator module.

Tests cover:
- ValidationRule dataclass creation
- ValidationResult add() method with various severities
- ToolResultValidator initialization and builtin rules
- add_rule() registration (global and action-specific)
- observe() middleware hook execution
- Built-in validation rules (truncated, error, empty)
"""

from unittest.mock import MagicMock

import pytest

from backend.orchestration.tool_pipeline import ToolInvocationContext
from backend.orchestration.tool_result_validator import (
    ToolResultValidator,
    ValidationResult,
    ValidationRule,
)
from backend.ledger.action import CmdRunAction
from backend.ledger.observation import (
    CmdOutputObservation,
    ErrorObservation,
    Observation,
)


class TestValidationRule:
    """Test ValidationRule dataclass."""

    def test_validation_rule_creation(self):
        """Should create ValidationRule with all fields."""
        check_func = MagicMock(return_value=None)
        rule = ValidationRule(
            name="test_rule",
            check=check_func,
            severity="warning",
        )

        assert rule.name == "test_rule"
        assert rule.check == check_func
        assert rule.severity == "warning"

    def test_validation_rule_default_severity(self):
        """Default severity should be 'warning'."""
        rule = ValidationRule(name="test", check=MagicMock())

        assert rule.severity == "warning"

    def test_validation_rule_custom_severity(self):
        """Should accept custom severity levels."""
        rule_error = ValidationRule(name="test", check=MagicMock(), severity="error")
        rule_block = ValidationRule(name="test2", check=MagicMock(), severity="block")

        assert rule_error.severity == "error"
        assert rule_block.severity == "block"


class TestValidationResult:
    """Test ValidationResult dataclass."""

    def test_validation_result_defaults(self):
        """ValidationResult should initialize with defaults."""
        result = ValidationResult()

        assert result.passed is True
        assert result.warnings == []
        assert result.errors == []
        assert result.blocked is False
        assert result.block_reason is None

    def test_add_warning(self):
        """add() with warning severity should append to warnings list."""
        result = ValidationResult()

        result.add("Warning message", "warning")

        assert len(result.warnings) == 1
        assert result.warnings[0] == "Warning message"
        assert result.passed is True  # Warnings don't fail
        assert result.errors == []

    def test_add_error(self):
        """add() with error severity should append to errors and fail."""
        result = ValidationResult()

        result.add("Error message", "error")

        assert len(result.errors) == 1
        assert result.errors[0] == "Error message"
        assert result.passed is False
        assert result.warnings == []

    def test_add_block(self):
        """add() with block severity should set blocked flag."""
        result = ValidationResult()

        result.add("Block message", "block")

        assert result.blocked is True
        assert result.block_reason == "Block message"
        assert result.passed is False

    def test_add_multiple_warnings(self):
        """add() should accumulate multiple warnings."""
        result = ValidationResult()

        result.add("Warning 1", "warning")
        result.add("Warning 2", "warning")

        assert len(result.warnings) == 2
        assert result.passed is True

    def test_add_multiple_errors(self):
        """add() should accumulate multiple errors."""
        result = ValidationResult()

        result.add("Error 1", "error")
        result.add("Error 2", "error")

        assert len(result.errors) == 2
        assert result.passed is False

    def test_add_mixed_severities(self):
        """add() should handle mixed severity levels."""
        result = ValidationResult()

        result.add("Warning", "warning")
        result.add("Error", "error")

        assert len(result.warnings) == 1
        assert len(result.errors) == 1
        assert result.passed is False


class TestToolResultValidatorInit:
    """Test ToolResultValidator initialization."""

    def test_init_creates_empty_rule_lists(self):
        """Should initialize with empty global and action rules."""
        validator = ToolResultValidator()

        assert isinstance(validator._global_rules, list)
        assert isinstance(validator._action_rules, dict)

    def test_init_registers_builtin_rules(self):
        """Should register built-in validation rules."""
        validator = ToolResultValidator()

        # Should have at least some global rules
        assert validator._global_rules

        # Check for specific built-in rules
        rule_names = {rule.name for rule in validator._global_rules}
        assert "output_size" in rule_names
        assert "error_observation" in rule_names
        assert "empty_result" in rule_names


class TestAddRule:
    """Test add_rule() method."""

    def test_add_global_rule(self):
        """Should add rule to global rules list."""
        validator = ToolResultValidator()
        check_func = MagicMock(return_value=None)

        initial_count = len(validator._global_rules)
        validator.add_rule("custom_rule", check_func)

        assert len(validator._global_rules) == initial_count + 1
        assert validator._global_rules[-1].name == "custom_rule"

    def test_add_action_specific_rule(self):
        """Should add rule to action-specific rules dict."""
        validator = ToolResultValidator()
        check_func = MagicMock(return_value=None)

        validator.add_rule("cmd_rule", check_func, action_type="CmdRunAction")

        assert "CmdRunAction" in validator._action_rules
        assert len(validator._action_rules["CmdRunAction"]) == 1
        assert validator._action_rules["CmdRunAction"][0].name == "cmd_rule"

    def test_add_multiple_rules_per_action(self):
        """Should allow multiple rules for same action type."""
        validator = ToolResultValidator()

        validator.add_rule("rule1", MagicMock(), action_type="CmdRunAction")
        validator.add_rule("rule2", MagicMock(), action_type="CmdRunAction")

        assert len(validator._action_rules["CmdRunAction"]) == 2

    def test_add_rule_with_custom_severity(self):
        """Should register rule with custom severity."""
        validator = ToolResultValidator()
        check_func = MagicMock(return_value=None)

        validator.add_rule("error_rule", check_func, severity="error")

        assert validator._global_rules[-1].severity == "error"

    def test_add_rule_default_severity_is_warning(self):
        """Default severity should be 'warning'."""
        validator = ToolResultValidator()
        check_func = MagicMock(return_value=None)

        validator.add_rule("default_rule", check_func)

        assert validator._global_rules[-1].severity == "warning"


class TestObserve:
    """Test observe() middleware hook."""

    @pytest.mark.asyncio
    async def test_observe_with_none_observation_returns_early(self):
        """Should return early if observation is None."""
        validator = ToolResultValidator()
        action = CmdRunAction(command="test")
        controller = MagicMock()
        state = MagicMock()
        ctx = ToolInvocationContext(controller=controller, action=action, state=state)

        await validator.observe(ctx, None)

        # Should not add validation_result to metadata
        assert "validation_result" not in ctx.metadata

    @pytest.mark.asyncio
    async def test_observe_appends_validation_block_to_content(self):
        validator = ToolResultValidator()
        controller = MagicMock()
        state = MagicMock()
        action = CmdRunAction(command="echo hi")
        ctx = ToolInvocationContext(controller=controller, action=action, state=state)

        # Create a large output to trigger built-in output_size warning.
        obs = CmdOutputObservation(content="x" * 120_000, command="echo hi")

        await validator.observe(ctx, obs)

        assert "<FORGE_RESULT_VALIDATION>" in obs.content

    @pytest.mark.asyncio
    async def test_observe_runs_global_rules(self):
        """Should run all global validation rules."""
        validator = ToolResultValidator()
        check_func = MagicMock(return_value=None)
        validator.add_rule("test_rule", check_func)

        action = CmdRunAction(command="test")
        obs = CmdOutputObservation(content="OK", command="test")
        controller = MagicMock()
        state = MagicMock()
        ctx = ToolInvocationContext(controller=controller, action=action, state=state)

        await validator.observe(ctx, obs)

        check_func.assert_called_once_with(ctx, obs)

    @pytest.mark.asyncio
    async def test_observe_runs_action_specific_rules(self):
        """Should run action-specific rules for matching action."""
        validator = ToolResultValidator()
        check_func = MagicMock(return_value=None)
        validator.add_rule("cmd_rule", check_func, action_type="CmdRunAction")

        action = CmdRunAction(command="test")
        obs = CmdOutputObservation(content="OK", command="test")
        controller = MagicMock()
        state = MagicMock()
        ctx = ToolInvocationContext(controller=controller, action=action, state=state)

        await validator.observe(ctx, obs)

        check_func.assert_called_once()

    @pytest.mark.asyncio
    async def test_observe_skips_non_matching_action_rules(self):
        """Should not run action-specific rules for different actions."""
        validator = ToolResultValidator()
        check_func = MagicMock(return_value=None)
        validator.add_rule("file_rule", check_func, action_type="FileReadAction")

        action = CmdRunAction(command="test")
        obs = CmdOutputObservation(content="OK", command="test")
        controller = MagicMock()
        state = MagicMock()
        ctx = ToolInvocationContext(controller=controller, action=action, state=state)

        await validator.observe(ctx, obs)

        check_func.assert_not_called()

    @pytest.mark.asyncio
    async def test_observe_stores_result_in_metadata(self):
        """Should store ValidationResult in context metadata."""
        validator = ToolResultValidator()

        action = CmdRunAction(command="test")
        obs = CmdOutputObservation(content="OK", command="test")
        controller = MagicMock()
        state = MagicMock()
        ctx = ToolInvocationContext(controller=controller, action=action, state=state)

        await validator.observe(ctx, obs)

        assert "validation_result" in ctx.metadata
        assert isinstance(ctx.metadata["validation_result"], ValidationResult)

    @pytest.mark.asyncio
    async def test_observe_handles_failing_rule(self):
        """Should add error to result when rule check returns message."""
        validator = ToolResultValidator()
        check_func = MagicMock(return_value="Validation failed")
        validator.add_rule("fail_rule", check_func, severity="error")

        action = CmdRunAction(command="test")
        obs = CmdOutputObservation(content="BAD", command="test")
        controller = MagicMock()
        state = MagicMock()
        ctx = ToolInvocationContext(controller=controller, action=action, state=state)

        await validator.observe(ctx, obs)

        result = ctx.metadata["validation_result"]
        assert result.passed is False
        assert result.errors

    @pytest.mark.asyncio
    async def test_observe_handles_blocking_rule(self):
        """Should block context when rule has block severity."""
        validator = ToolResultValidator()
        check_func = MagicMock(return_value="Blocked")
        validator.add_rule("block_rule", check_func, severity="block")

        action = CmdRunAction(command="test")
        obs = CmdOutputObservation(content="BAD", command="test")
        controller = MagicMock()
        state = MagicMock()
        ctx = ToolInvocationContext(controller=controller, action=action, state=state)
        mock_block = cast(Any, ctx)
        mock_block.block = MagicMock()

        await validator.observe(ctx, obs)

        mock_block.block.assert_called_once()
        call_args = mock_block.block.call_args
        assert "RESULT VALIDATION BLOCKED" in call_args.kwargs["reason"]

    @pytest.mark.asyncio
    async def test_observe_gracefully_handles_rule_exception(self):
        """Should continue when validation rule raises exception."""
        validator = ToolResultValidator()

        def failing_check(ctx, obs):
            raise RuntimeError("Rule crashed")

        validator.add_rule("crash_rule", failing_check)

        action = CmdRunAction(command="test")
        CmdOutputObservation(content="OK", command="test")
        controller = MagicMock()
        state = MagicMock()
        ToolInvocationContext(controller=controller, action=action, state=state)

    @pytest.mark.asyncio
    async def test_output_size_rule_warns_on_large_content(self):
        """output_size rule should warn when content > 100k chars."""
        validator = ToolResultValidator()

        action = CmdRunAction(command="test")
        large_content = "x" * 150000
        obs = CmdOutputObservation(content=large_content, command="test", hidden=True)
        controller = MagicMock()
        state = MagicMock()
        ctx = ToolInvocationContext(controller=controller, action=action, state=state)

        await validator.observe(ctx, obs)

        result = ctx.metadata["validation_result"]
        assert result.warnings
        # Check for truncation warning
        warning_text = " ".join(result.warnings)
        assert (
            "truncated" in warning_text.lower() or "incomplete" in warning_text.lower()
        )

    @pytest.mark.asyncio
    async def test_output_size_rule_passes_on_small_content(self):
        """output_size rule should pass when content is small."""
        validator = ToolResultValidator()

        action = CmdRunAction(command="test")
        obs = CmdOutputObservation(content="small output", command="test")
        controller = MagicMock()
        state = MagicMock()
        ctx = ToolInvocationContext(controller=controller, action=action, state=state)

        await validator.observe(ctx, obs)

        result = ctx.metadata["validation_result"]
        # Should either have no warnings or no truncation warnings
        truncation_warnings = [w for w in result.warnings if "truncated" in w.lower()]
        assert not truncation_warnings

    @pytest.mark.asyncio
    async def test_error_observation_rule_warns_on_error(self):
        """error_observation rule should warn when obs is ErrorObservation."""
        validator = ToolResultValidator()

        action = CmdRunAction(command="test")
        obs = ErrorObservation(content="Command failed")
        controller = MagicMock()
        state = MagicMock()
        ctx = ToolInvocationContext(controller=controller, action=action, state=state)

        await validator.observe(ctx, obs)

        result = ctx.metadata["validation_result"]
        assert result.warnings
        # Check for error warning
        warning_text = " ".join(result.warnings)
        assert "error" in warning_text.lower()

    @pytest.mark.asyncio
    async def test_error_observation_rule_passes_on_normal_obs(self):
        """error_observation rule should pass for non-error observations."""
        validator = ToolResultValidator()

        action = CmdRunAction(command="test")
        obs = CmdOutputObservation(content="Success", command="test")
        controller = MagicMock()
        state = MagicMock()
        ctx = ToolInvocationContext(controller=controller, action=action, state=state)

        await validator.observe(ctx, obs)

        result = ctx.metadata["validation_result"]
        # Should not have error observation warnings
        error_warnings = [
            w for w in result.warnings if "tool returned error" in w.lower()
        ]
        assert not error_warnings

    @pytest.mark.asyncio
    async def test_empty_result_rule_warns_on_empty_content(self):
        """empty_result rule should warn when content is empty."""
        validator = ToolResultValidator()

        action = CmdRunAction(command="test")
        obs = CmdOutputObservation(content="   ", command="test")
        controller = MagicMock()
        state = MagicMock()
        ctx = ToolInvocationContext(controller=controller, action=action, state=state)

        await validator.observe(ctx, obs)

        result = ctx.metadata["validation_result"]
        assert result.warnings
        # Check for empty warning
        warning_text = " ".join(result.warnings)
        assert "empty" in warning_text.lower()

    @pytest.mark.asyncio
    async def test_empty_result_rule_passes_on_content(self):
        """empty_result rule should pass when content is non-empty."""
        validator = ToolResultValidator()

        action = CmdRunAction(command="test")
        obs = CmdOutputObservation(content="Some content", command="test")
        controller = MagicMock()
        state = MagicMock()
        ctx = ToolInvocationContext(controller=controller, action=action, state=state)

        await validator.observe(ctx, obs)

        result = ctx.metadata["validation_result"]
        # Should not have empty result warnings
        empty_warnings = [w for w in result.warnings if "empty" in w.lower()]
        assert not empty_warnings

    @pytest.mark.asyncio
    async def test_empty_result_handles_none_content(self):
        """empty_result rule should handle None content gracefully."""
        validator = ToolResultValidator()

        action = CmdRunAction(command="test")
        # Create observation with no content attribute
        obs = MagicMock(spec=Observation)
        obs.content = None
        controller = MagicMock()
        state = MagicMock()
        ctx = ToolInvocationContext(controller=controller, action=action, state=state)

        # Should not raise
        await validator.observe(ctx, obs)

        assert "validation_result" in ctx.metadata
