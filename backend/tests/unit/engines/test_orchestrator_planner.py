"""Tests for backend.engines.orchestrator.planner — message and tool-description helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

from backend.core.enums import ActionSecurityRisk
from backend.engines.orchestrator.orchestrator import Orchestrator
from backend.engines.orchestrator.planner import (
    OrchestratorPlanner,
    _shorten_tool_description,
)
from backend.events.action.files import FileEditAction, FileWriteAction
from backend.events.observation import ErrorObservation


# We test the static/pure methods by creating a planner with minimal mocks.
def _make_planner():
    """Create a planner with None dependencies for testing pure methods."""
    return object.__new__(OrchestratorPlanner)


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


class TestShortenToolDescription:
    def test_preserves_dr_and_url_without_splitting_first_period(self):
        long_tail = "x" * 120
        desc = f"Call Dr. Smith at https://ex.com/a.b. Second sentence.{long_tail}"
        out = _shorten_tool_description(desc, max_len=80)
        assert "Dr." in out
        assert len(out) <= 85

class TestApplyDescriptionTiers:
    def test_trims_long_description_for_used_tool(self):
        p = _make_planner()
        p._tools_used_this_session = {"used_tool"}
        long_desc = (
            "Does something useful. Also handles Dr. edge cases. " + "word " * 40
        )
        tools = [
            {
                "type": "function",
                "function": {"name": "used_tool", "description": long_desc},
            },
        ]
        out = p._apply_description_tiers(tools)
        trimmed = out[0]["function"]["description"]
        assert len(trimmed) <= 85
        assert "Dr." in trimmed


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
