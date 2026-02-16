"""Tests for OrchestratorSafetyManager static helpers in backend.engines.orchestrator.safety."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.engines.orchestrator.safety import OrchestratorSafetyManager


class TestToolFunctionName:
    def test_from_tool_call_metadata(self):
        action = SimpleNamespace(
            tool_call_metadata=SimpleNamespace(function_name="execute_bash"),
            action=None,
        )
        assert OrchestratorSafetyManager._tool_function_name(action) == "execute_bash"

    def test_from_action_attr(self):
        action = SimpleNamespace(tool_call_metadata=None, action="run_cmd")
        assert OrchestratorSafetyManager._tool_function_name(action) == "run_cmd"

    def test_none_when_no_name(self):
        action = SimpleNamespace(tool_call_metadata=None, action=None)
        assert OrchestratorSafetyManager._tool_function_name(action) is None

    def test_empty_function_name_skipped(self):
        action = SimpleNamespace(
            tool_call_metadata=SimpleNamespace(function_name="   "),
            action="fallback",
        )
        assert OrchestratorSafetyManager._tool_function_name(action) == "fallback"

    def test_metadata_without_function_name(self):
        action = SimpleNamespace(
            tool_call_metadata=SimpleNamespace(), action="act"
        )
        assert OrchestratorSafetyManager._tool_function_name(action) == "act"


class TestShouldWarnOnDetection:
    def test_no_detection(self):
        assert OrchestratorSafetyManager._should_warn_on_detection({}) is False

    def test_none_detection(self):
        assert OrchestratorSafetyManager._should_warn_on_detection(None) is False

    def test_not_hallucinated(self):
        assert (
            OrchestratorSafetyManager._should_warn_on_detection(
                {"hallucinated": False}
            )
            is False
        )

    def test_critical_severity(self):
        assert (
            OrchestratorSafetyManager._should_warn_on_detection(
                {"hallucinated": True, "severity": "critical"}
            )
            is True
        )

    def test_high_severity(self):
        assert (
            OrchestratorSafetyManager._should_warn_on_detection(
                {"hallucinated": True, "severity": "high"}
            )
            is True
        )

    def test_low_severity_no_warn(self):
        assert (
            OrchestratorSafetyManager._should_warn_on_detection(
                {"hallucinated": True, "severity": "low"}
            )
            is False
        )

    def test_medium_severity_no_warn(self):
        assert (
            OrchestratorSafetyManager._should_warn_on_detection(
                {"hallucinated": True, "severity": "medium"}
            )
            is False
        )


class TestBuildWarningContent:
    def test_with_claimed_and_missing(self):
        content = OrchestratorSafetyManager._build_warning_content(
            ["wrote file.py", "ran tests"], ["file_write", "execute_bash"]
        )
        assert "wrote file.py" in content
        assert "ran tests" in content
        assert "file_write" in content
        assert "execute_bash" in content
        assert "RELIABILITY WARNING" in content

    def test_no_missing_tools(self):
        content = OrchestratorSafetyManager._build_warning_content(
            ["did something"], []
        )
        assert "Required tools not called" not in content
        assert "did something" in content

    def test_empty_everything(self):
        content = OrchestratorSafetyManager._build_warning_content([], [])
        assert "RELIABILITY WARNING" in content


class TestDeriveToolsCalled:
    def test_extracts_tool_names(self):
        mgr = OrchestratorSafetyManager(None, None)
        actions = [
            SimpleNamespace(
                tool_call_metadata=SimpleNamespace(function_name="bash"),
                action=None,
            ),
            SimpleNamespace(tool_call_metadata=None, action="editor"),
        ]
        result = mgr._derive_tools_called(actions)
        assert result == ["bash", "editor"]

    def test_empty_actions(self):
        mgr = OrchestratorSafetyManager(None, None)
        assert mgr._derive_tools_called([]) == []

    def test_none_actions(self):
        mgr = OrchestratorSafetyManager(None, None)
        assert mgr._derive_tools_called(None) == []

    def test_skips_unnamed(self):
        mgr = OrchestratorSafetyManager(None, None)
        actions = [SimpleNamespace(tool_call_metadata=None, action=None)]
        assert mgr._derive_tools_called(actions) == []


class TestShouldEnforceTools:
    def test_no_message(self):
        mgr = OrchestratorSafetyManager(None, None)
        assert mgr.should_enforce_tools(None, None, "auto") == "auto"

    def test_no_anti_hallucination(self):
        mgr = OrchestratorSafetyManager(None, None)
        assert mgr.should_enforce_tools("create a file", None, "required") == "required"
