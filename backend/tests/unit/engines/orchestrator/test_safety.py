"""Comprehensive unit tests for OrchestratorSafetyManager."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.engines.orchestrator.safety import OrchestratorSafetyManager
from backend.events.action import MessageAction, NullAction


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _manager(
    anti_hallucination=None,
    hallucination_detector=None,
) -> OrchestratorSafetyManager:
    return OrchestratorSafetyManager(
        anti_hallucination=anti_hallucination,
        hallucination_detector=hallucination_detector,
    )


def _mock_anti() -> MagicMock:
    ah = MagicMock()
    ah.turn_counter = 0
    ah.should_enforce_tools.return_value = "auto"
    ah.validate_response.return_value = (True, None)
    ah.inject_verification_commands.side_effect = lambda actions, turn: actions
    return ah


def _mock_detector(hallucinated: bool = False, severity: str = "low") -> MagicMock:
    det = MagicMock()
    if hallucinated:
        det.detect_text_hallucination.return_value = {
            "hallucinated": True,
            "severity": severity,
            "claimed_operations": ["I created file.py"],
            "missing_tools": ["edit_file"],
        }
    else:
        det.detect_text_hallucination.return_value = {"hallucinated": False}
    return det


# ---------------------------------------------------------------------------
# should_enforce_tools
# ---------------------------------------------------------------------------

class TestShouldEnforceTools:
    def test_no_last_message_returns_default(self):
        mgr = _manager()
        state = MagicMock()
        result = mgr.should_enforce_tools(None, state, default="none")
        assert result == "none"

    def test_empty_message_returns_default(self):
        mgr = _manager()
        state = MagicMock()
        result = mgr.should_enforce_tools("", state, default="none")
        assert result == "none"

    def test_no_anti_hallucination_returns_default(self):
        mgr = _manager(anti_hallucination=None)
        state = MagicMock()
        result = mgr.should_enforce_tools("build a thing", state, default="required")
        assert result == "required"

    def test_delegates_to_anti_hallucination(self):
        ah = _mock_anti()
        ah.should_enforce_tools.return_value = "strict"
        mgr = _manager(anti_hallucination=ah)
        state = MagicMock()
        result = mgr.should_enforce_tools("create a module", state, default="none")
        assert result == "strict"
        ah.should_enforce_tools.assert_called_once()

    def test_exception_falls_back_to_default(self):
        ah = _mock_anti()
        ah.should_enforce_tools.side_effect = RuntimeError("oops")
        mgr = _manager(anti_hallucination=ah)
        state = MagicMock()
        result = mgr.should_enforce_tools("task", state, default="fallback")
        assert result == "fallback"


# ---------------------------------------------------------------------------
# apply — no hallucination, pass-through
# ---------------------------------------------------------------------------

class TestApplyPassthrough:
    def test_no_anti_no_detector_returns_true_and_actions(self):
        mgr = _manager()
        actions = [NullAction()]
        ok, out = mgr.apply("response", actions)
        assert ok is True
        assert out is actions

    def test_valid_response_passes_through(self):
        ah = _mock_anti()
        mgr = _manager(anti_hallucination=ah)
        actions = [NullAction()]
        ok, out = mgr.apply("clean response", actions)
        assert ok is True

    def test_inject_verification_increments_turn_counter(self):
        ah = _mock_anti()
        mgr = _manager(anti_hallucination=ah)
        mgr.apply("text", [NullAction()])
        assert ah.turn_counter == 1
        mgr.apply("text", [NullAction()])
        assert ah.turn_counter == 2


# ---------------------------------------------------------------------------
# _pre_validate — blocking
# ---------------------------------------------------------------------------

class TestPreValidateBlocking:
    def test_invalid_response_returns_false_and_message_action(self):
        ah = _mock_anti()
        ah.validate_response.return_value = (False, "Bad response!")
        mgr = _manager(anti_hallucination=ah)
        ok, actions = mgr.apply("hallucinated text", [])
        assert ok is False
        assert len(actions) == 1
        assert isinstance(actions[0], MessageAction)
        assert "Bad response!" in actions[0].content

    def test_blocking_with_none_error_message(self):
        ah = _mock_anti()
        ah.validate_response.return_value = (False, None)
        mgr = _manager(anti_hallucination=ah)
        ok, actions = mgr.apply("bad", [])
        assert ok is False
        # Should include fallback message
        assert isinstance(actions[0], MessageAction)


# ---------------------------------------------------------------------------
# _detect_and_warn
# ---------------------------------------------------------------------------

class TestDetectAndWarn:
    def test_low_severity_hallucination_no_warning(self):
        """Low/medium severity should not prepend a warning action."""
        det = _mock_detector(hallucinated=True, severity="low")
        mgr = _manager(hallucination_detector=det)
        initial = [NullAction()]
        ok, out = mgr.apply("I created file.py", initial)
        assert ok is True
        assert all(not isinstance(a, MessageAction) for a in out)

    def test_critical_severity_prepends_warning(self):
        det = _mock_detector(hallucinated=True, severity="critical")
        mgr = _manager(hallucination_detector=det)
        initial = [NullAction()]
        ok, out = mgr.apply("I created file.py", initial)
        assert ok is True
        assert isinstance(out[0], MessageAction)
        assert "WARNING" in out[0].content or "RELIABILITY" in out[0].content

    def test_high_severity_prepends_warning(self):
        det = _mock_detector(hallucinated=True, severity="high")
        mgr = _manager(hallucination_detector=det)
        initial = [NullAction()]
        ok, out = mgr.apply("I edited util.py", initial)
        assert ok is True
        assert isinstance(out[0], MessageAction)

    def test_no_hallucination_no_warning(self):
        det = _mock_detector(hallucinated=False)
        mgr = _manager(hallucination_detector=det)
        initial = [NullAction()]
        ok, out = mgr.apply("clean response", initial)
        assert ok is True
        assert not any(isinstance(a, MessageAction) for a in out)


# ---------------------------------------------------------------------------
# _derive_tools_called
# ---------------------------------------------------------------------------

class TestDeriveToolsCalled:
    def setup_method(self):
        self.mgr = _manager()

    def test_empty_actions(self):
        assert self.mgr._derive_tools_called([]) == []

    def test_none_actions(self):
        assert self.mgr._derive_tools_called(None) == []

    def test_action_with_tool_call_metadata(self):
        action = MagicMock()
        meta = MagicMock()
        meta.function_name = "edit_file"
        action.tool_call_metadata = meta
        result = self.mgr._derive_tools_called([action])
        assert "edit_file" in result

    def test_action_with_action_attribute(self):
        action = MagicMock(spec=[])
        action.action = "run_bash"
        result = self.mgr._derive_tools_called([action])
        assert "run_bash" in result

    def test_action_without_any_identifier(self):
        action = MagicMock(spec=[])
        result = self.mgr._derive_tools_called([action])
        assert result == []


# ---------------------------------------------------------------------------
# _tool_function_name (static method)
# ---------------------------------------------------------------------------

class TestToolFunctionName:
    def test_from_tool_call_metadata(self):
        action = MagicMock()
        meta = MagicMock()
        meta.function_name = "str_replace_editor"
        action.tool_call_metadata = meta
        result = OrchestratorSafetyManager._tool_function_name(action)
        assert result == "str_replace_editor"

    def test_empty_function_name_falls_through(self):
        action = MagicMock()
        meta = MagicMock()
        meta.function_name = "  "  # whitespace
        action.tool_call_metadata = meta
        action.action = "run"
        result = OrchestratorSafetyManager._tool_function_name(action)
        assert result == "run"

    def test_no_metadata_no_action(self):
        action = MagicMock(spec=[])
        result = OrchestratorSafetyManager._tool_function_name(action)
        assert result is None


# ---------------------------------------------------------------------------
# _should_warn_on_detection (static)
# ---------------------------------------------------------------------------

class TestShouldWarnOnDetection:
    def test_none_returns_false(self):
        assert OrchestratorSafetyManager._should_warn_on_detection(None) is False

    def test_not_hallucinated_returns_false(self):
        assert OrchestratorSafetyManager._should_warn_on_detection({"hallucinated": False}) is False

    def test_low_severity_returns_false(self):
        d = {"hallucinated": True, "severity": "low"}
        assert OrchestratorSafetyManager._should_warn_on_detection(d) is False

    def test_medium_severity_returns_false(self):
        d = {"hallucinated": True, "severity": "medium"}
        assert OrchestratorSafetyManager._should_warn_on_detection(d) is False

    def test_high_severity_returns_true(self):
        d = {"hallucinated": True, "severity": "high"}
        assert OrchestratorSafetyManager._should_warn_on_detection(d) is True

    def test_critical_severity_returns_true(self):
        d = {"hallucinated": True, "severity": "critical"}
        assert OrchestratorSafetyManager._should_warn_on_detection(d) is True


# ---------------------------------------------------------------------------
# _build_warning_content (static)
# ---------------------------------------------------------------------------

class TestBuildWarningContent:
    def test_contains_claimed_operations(self):
        content = OrchestratorSafetyManager._build_warning_content(
            ["I created foo.py"], ["edit_file"]
        )
        assert "foo.py" in content

    def test_contains_missing_tools(self):
        content = OrchestratorSafetyManager._build_warning_content(
            ["claimed"], ["some_tool"]
        )
        assert "some_tool" in content

    def test_no_missing_tools_section_absent(self):
        content = OrchestratorSafetyManager._build_warning_content(
            ["something"], []
        )
        assert "Required tools not called" not in content

    def test_contains_warning_header(self):
        content = OrchestratorSafetyManager._build_warning_content([], [])
        assert "WARNING" in content

    def test_multiple_claimed_ops(self):
        content = OrchestratorSafetyManager._build_warning_content(
            ["op1", "op2", "op3"], []
        )
        assert "op1" in content and "op2" in content and "op3" in content
