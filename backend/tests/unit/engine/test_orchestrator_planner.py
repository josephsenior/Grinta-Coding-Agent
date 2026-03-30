"""Tests for backend.engine.planner — message and tool-description helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.core.enums import ActionSecurityRisk
from backend.engine.orchestrator import Orchestrator
from backend.engine.planner import OrchestratorPlanner, _maybe_log_prompt_metrics
from backend.ledger.action.files import FileEditAction, FileWriteAction
from backend.ledger.observation import ErrorObservation


# We test the static/pure methods by creating a planner with minimal mocks.
def _make_planner():
    """Create a planner with None dependencies for testing pure methods."""
    return object.__new__(OrchestratorPlanner)


class TestPromptMetricsLogging:
    def test_logs_when_app_debug_prompt_metrics_enabled(self):
        with patch.dict(
            "os.environ",
            {"APP_DEBUG_PROMPT_METRICS": "1"},
            clear=False,
        ), patch("backend.engine.planner.logger") as mock_logger:
            _maybe_log_prompt_metrics([
                {"role": "system", "content": "hello"},
                {"role": "user", "content": "world"},
            ])

        mock_logger.info.assert_called_once_with(
            "APP_DEBUG_PROMPT_METRICS: system_messages=%s chars_each=%s chars_total=%s",
            1,
            [5],
            5,
        )


class TestGetLastUserMessage:
    def test_finds_last_user_message(self):
        p = _make_planner()
        messages = [
            {"role": "user", "content": "First"},
            {"role": "assistant", "content": "Response"},
            {"role": "user", "content": "Second"},
        ]
        assert p._get_last_user_message(messages) == "Second"

    def test_no_user_message(self):
        p = _make_planner()
        messages = [{"role": "assistant", "content": "Hi"}]
        assert p._get_last_user_message(messages) is None

    def test_empty_messages(self):
        p = _make_planner()
        assert p._get_last_user_message([]) is None

    def test_user_with_empty_content(self):
        p = _make_planner()
        messages = [{"role": "user"}]
        assert p._get_last_user_message(messages) == ""


class TestOrchestratorPromptTierFromHistory:
    def test_debug_when_error_observation_in_window(self):
        orch = Orchestrator.__new__(Orchestrator)
        mock_pm = MagicMock()
        object.__setattr__(orch, "_prompt_manager", mock_pm)
        state = MagicMock()
        state.history = [
            FileEditAction(path="a.py", security_risk=ActionSecurityRisk.LOW),
            ErrorObservation(content="tool blew up"),
        ]
        orch._set_prompt_tier_from_recent_history(state)
        mock_pm.set_prompt_tier.assert_called_with("debug")

    def test_base_when_only_low_risk_file_edit(self):
        orch = Orchestrator.__new__(Orchestrator)
        mock_pm = MagicMock()
        object.__setattr__(orch, "_prompt_manager", mock_pm)
        state = MagicMock()
        state.history = [FileEditAction(path="a.py", security_risk=ActionSecurityRisk.LOW)]
        orch._set_prompt_tier_from_recent_history(state)
        mock_pm.set_prompt_tier.assert_called_with("base")

    def test_debug_when_file_write_high_security_risk(self):
        orch = Orchestrator.__new__(Orchestrator)
        mock_pm = MagicMock()
        object.__setattr__(orch, "_prompt_manager", mock_pm)
        state = MagicMock()
        state.history = [
            FileWriteAction(path="x.sh", content="", security_risk=ActionSecurityRisk.HIGH),
        ]
        orch._set_prompt_tier_from_recent_history(state)
        mock_pm.set_prompt_tier.assert_called_with("debug")
