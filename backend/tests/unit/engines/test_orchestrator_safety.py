"""Tests for backend.engines.orchestrator.safety.OrchestratorSafetyManager."""

from __future__ import annotations

from unittest.mock import MagicMock
from typing import cast


from backend.engines.orchestrator.safety import OrchestratorSafetyManager


# ── helpers ──────────────────────────────────────────────────────────


def _manager(anti_hallucination=None, hallucination_detector=None):
    return OrchestratorSafetyManager(anti_hallucination, hallucination_detector)


# ── should_enforce_tools ─────────────────────────────────────────────


class TestShouldEnforceTools:
    def test_no_message(self):
        m = _manager(anti_hallucination=MagicMock())
        assert m.should_enforce_tools(None, MagicMock(), "auto") == "auto"

    def test_no_anti_hallucination(self):
        m = _manager(anti_hallucination=None)
        assert m.should_enforce_tools("hello", MagicMock(), "auto") == "auto"

    def test_delegates(self):
        ah = MagicMock()
        ah.should_enforce_tools.return_value = "required"
        m = _manager(anti_hallucination=ah)
        result = m.should_enforce_tools("hello", MagicMock(), "auto")
        assert result == "required"

    def test_exception_returns_default(self):
        ah = MagicMock()
        ah.should_enforce_tools.side_effect = RuntimeError("boom")
        m = _manager(anti_hallucination=ah)
        assert m.should_enforce_tools("hello", MagicMock(), "fallback") == "fallback"


# ── apply (full pipeline) ───────────────────────────────────────────


class TestApply:
    def test_no_modules(self):
        m = _manager()
        ok, actions = m.apply("text", [MagicMock()])
        assert ok is True
        assert len(actions) == 1

    def test_blocked_by_anti_hallucination(self):
        ah = MagicMock()
        ah.validate_response.return_value = (False, "blocked!")
        m = _manager(anti_hallucination=ah)
        ok, actions = m.apply("bad text", [MagicMock()])
        assert ok is False
        assert len(actions) == 1
        assert "blocked!" in actions[0].content

    def test_valid_passes_through(self):
        ah = MagicMock()
        ah.validate_response.return_value = (True, None)
        ah.turn_counter = 0
        ah.inject_verification_commands.return_value = [MagicMock()]
        m = _manager(anti_hallucination=ah)
        ok, actions = m.apply("good text", [MagicMock()])
        assert ok is True


# ── _tool_function_name ──────────────────────────────────────────────


class TestToolFunctionName:
    def test_from_metadata(self):
        action = MagicMock()
        action.tool_call_metadata.function_name = "my_tool"
        assert OrchestratorSafetyManager._tool_function_name(action) == "my_tool"

    def test_from_action_attr(self):
        action = MagicMock(spec=["action"])
        action.action = "edit"
        assert OrchestratorSafetyManager._tool_function_name(action) == "edit"

    def test_none(self):
        action = MagicMock(spec=[])
        assert OrchestratorSafetyManager._tool_function_name(action) is None


# ── _should_warn_on_detection ────────────────────────────────────────


class TestShouldWarnOnDetection:
    def test_none(self):
        assert not OrchestratorSafetyManager._should_warn_on_detection(cast(dict, None))

    def test_not_hallucinated(self):
        assert not OrchestratorSafetyManager._should_warn_on_detection(
            {"hallucinated": False}
        )

    def test_low_severity(self):
        assert not OrchestratorSafetyManager._should_warn_on_detection(
            {"hallucinated": True, "severity": "low"}
        )

    def test_critical(self):
        assert OrchestratorSafetyManager._should_warn_on_detection(
            {"hallucinated": True, "severity": "critical"}
        )


# ── _build_warning_content ───────────────────────────────────────────


class TestBuildWarningContent:
    def test_basic(self):
        content = OrchestratorSafetyManager._build_warning_content(
            ["created file"], ["write_file"]
        )
        assert "created file" in content
        assert "write_file" in content

    def test_empty_missing(self):
        content = OrchestratorSafetyManager._build_warning_content(["op"], [])
        assert "Required tools" not in content


# ── hallucination detection in pipeline ──────────────────────────────


class TestDetectAndWarn:
    def test_critical_detection_prepends_warning(self):
        ah = MagicMock()
        ah.validate_response.return_value = (True, None)
        ah.turn_counter = 0
        ah.inject_verification_commands.side_effect = lambda actions, turn: actions

        hd = MagicMock()
        hd.detect_text_hallucination.return_value = {
            "hallucinated": True,
            "severity": "critical",
            "claimed_operations": ["wrote file"],
            "missing_tools": ["write"],
        }

        m = _manager(anti_hallucination=ah, hallucination_detector=hd)
        action = MagicMock()
        action.tool_call_metadata.function_name = "some_tool"
        ok, actions = m.apply("text", [action])
        assert ok is True
        # Warning message should be prepended
        assert len(actions) >= 2
        assert "WARNING" in actions[0].content
