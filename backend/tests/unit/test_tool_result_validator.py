"""Unit tests for backend.controller.tool_result_validator — observation validation."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.controller.tool_result_validator import (
    ToolResultValidator,
    ValidationResult,
    ValidationRule,
)
from backend.controller.tool_pipeline import ToolInvocationContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ctx(action_type: str = "CmdRunAction") -> ToolInvocationContext:
    action = MagicMock()
    type(action).__name__ = action_type
    controller = MagicMock()
    state = MagicMock()
    return ToolInvocationContext(
        controller=controller,
        action=action,
        state=state,
        metadata={},
    )


def _make_observation(content: str = "some output"):
    obs = MagicMock()
    obs.content = content
    return obs


# ---------------------------------------------------------------------------
# ValidationResult
# ---------------------------------------------------------------------------


class TestValidationResult:
    def test_default(self):
        vr = ValidationResult()
        assert vr.passed is True
        assert vr.warnings == []
        assert vr.errors == []
        assert vr.blocked is False

    def test_add_warning(self):
        vr = ValidationResult()
        vr.add("minor issue", "warning")
        assert vr.passed is True  # warnings don't fail
        assert len(vr.warnings) == 1

    def test_add_error(self):
        vr = ValidationResult()
        vr.add("bad thing", "error")
        assert vr.passed is False
        assert len(vr.errors) == 1

    def test_add_block(self):
        vr = ValidationResult()
        vr.add("critical", "block")
        assert vr.passed is False
        assert vr.blocked is True
        assert vr.block_reason == "critical"


# ---------------------------------------------------------------------------
# ValidationRule
# ---------------------------------------------------------------------------


class TestValidationRule:
    def test_fields(self):
        rule = ValidationRule(
            name="test_rule",
            check=lambda ctx, obs: None,
            severity="error",
        )
        assert rule.name == "test_rule"
        assert rule.severity == "error"


# ---------------------------------------------------------------------------
# Constructor & built-in rules
# ---------------------------------------------------------------------------


class TestToolResultValidatorInit:
    def test_builtin_rules_registered(self):
        v = ToolResultValidator()
        assert len(v._global_rules) >= 3  # output_size, error_observation, empty_result

    def test_rule_names(self):
        v = ToolResultValidator()
        names = {r.name for r in v._global_rules}
        assert "output_size" in names
        assert "error_observation" in names
        assert "empty_result" in names


# ---------------------------------------------------------------------------
# add_rule
# ---------------------------------------------------------------------------


class TestAddRule:
    def test_add_global(self):
        v = ToolResultValidator()
        initial = len(v._global_rules)
        v.add_rule("custom", lambda ctx, obs: None)
        assert len(v._global_rules) == initial + 1

    def test_add_action_specific(self):
        v = ToolResultValidator()
        v.add_rule("custom", lambda ctx, obs: None, action_type="CmdRunAction")
        assert "CmdRunAction" in v._action_rules
        assert len(v._action_rules["CmdRunAction"]) == 1


# ---------------------------------------------------------------------------
# observe — built-in rules
# ---------------------------------------------------------------------------


class TestObserveBuiltins:
    @pytest.mark.asyncio
    async def test_normal_output_passes(self):
        v = ToolResultValidator()
        ctx = _make_ctx()
        obs = _make_observation("some normal output")
        await v.observe(ctx, obs)
        result = ctx.metadata.get("validation_result")
        # warnings possible but should still pass
        assert result is not None

    @pytest.mark.asyncio
    async def test_none_observation_skips(self):
        v = ToolResultValidator()
        ctx = _make_ctx()
        await v.observe(ctx, None)
        assert "validation_result" not in ctx.metadata

    @pytest.mark.asyncio
    async def test_empty_output_warning(self):
        v = ToolResultValidator()
        ctx = _make_ctx()
        obs = _make_observation("")
        await v.observe(ctx, obs)
        result = ctx.metadata.get("validation_result")
        assert result is not None
        assert any("empty" in w.lower() for w in result.warnings)

    @pytest.mark.asyncio
    async def test_truncated_output_warning(self):
        v = ToolResultValidator()
        ctx = _make_ctx()
        obs = _make_observation("x" * 200_000)
        await v.observe(ctx, obs)
        result = ctx.metadata.get("validation_result")
        assert result is not None
        assert any("truncated" in w.lower() for w in result.warnings)

    @pytest.mark.asyncio
    async def test_error_observation_warning(self):
        from backend.events.observation import ErrorObservation

        v = ToolResultValidator()
        ctx = _make_ctx()
        obs = ErrorObservation(content="command not found")
        await v.observe(ctx, obs)
        result = ctx.metadata.get("validation_result")
        assert result is not None
        assert any("error" in w.lower() for w in result.warnings)


# ---------------------------------------------------------------------------
# Custom rules
# ---------------------------------------------------------------------------


class TestCustomRules:
    @pytest.mark.asyncio
    async def test_custom_blocking_rule(self):
        v = ToolResultValidator()
        v.add_rule(
            "danger",
            lambda ctx, obs: "too dangerous" if "rm -rf" in obs.content else None,
            severity="block",
        )
        ctx = _make_ctx()
        obs = _make_observation("rm -rf /")
        await v.observe(ctx, obs)
        result = ctx.metadata["validation_result"]
        assert result.blocked is True
        assert "too dangerous" in result.block_reason

    @pytest.mark.asyncio
    async def test_custom_error_rule(self):
        v = ToolResultValidator()
        v.add_rule(
            "length_check",
            lambda ctx, obs: "too short" if len(obs.content) < 5 else None,
            severity="error",
        )
        ctx = _make_ctx()
        obs = _make_observation("hi")
        await v.observe(ctx, obs)
        result = ctx.metadata["validation_result"]
        assert result.passed is False
        assert "too short" in result.errors

    @pytest.mark.asyncio
    async def test_action_specific_rule_only_fires_for_type(self):
        v = ToolResultValidator()
        v.add_rule(
            "cmd_only",
            lambda ctx, obs: "found" if True else None,
            severity="warning",
            action_type="CmdRunAction",
        )
        ctx_cmd = _make_ctx("CmdRunAction")
        obs = _make_observation("output")
        await v.observe(ctx_cmd, obs)
        assert any(
            "found" in w for w in ctx_cmd.metadata["validation_result"].warnings
        )

        ctx_edit = _make_ctx("FileEditAction")
        await v.observe(ctx_edit, obs)
        # "cmd_only" should NOT fire for FileEditAction
        result = ctx_edit.metadata.get("validation_result")
        if result:
            assert "found" not in result.warnings

    @pytest.mark.asyncio
    async def test_rule_exception_handled(self):
        v = ToolResultValidator()
        v.add_rule("crasher", lambda ctx, obs: (_ for _ in ()).throw(RuntimeError("boom")))
        ctx = _make_ctx()
        obs = _make_observation("ok")
        # Should not raise
        await v.observe(ctx, obs)
