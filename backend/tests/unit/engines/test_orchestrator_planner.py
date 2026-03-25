"""Tests for backend.engines.orchestrator.planner — pure regex and message helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

from backend.core.enums import ActionSecurityRisk
from backend.engines.orchestrator.orchestrator import Orchestrator
from backend.engines.orchestrator.planner import (
    OrchestratorPlanner,
    _shorten_tool_description,
)
from backend.engines.orchestrator.behavioral_hints import BehavioralHintsBuilder
from backend.engines.orchestrator.error_learner import SessionErrorLearner
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


class TestPatternConstants:
    pass

# ───────────────────────────────────────────────────────────────────────
# SessionErrorLearner unit tests
# ───────────────────────────────────────────────────────────────────────


class TestSessionErrorLearner:
    def test_no_failures_returns_empty(self):
        learner = SessionErrorLearner()
        assert learner.get_hypotheses() == []

    def test_single_failure_no_hint(self):
        learner = SessionErrorLearner()
        learner.record_failure("str_replace_editor", "[ERROR] no match found", 1)
        # Only one failure — threshold is 2
        assert learner.get_hypotheses() == []

    def test_repeated_failure_generates_hint(self):
        learner = SessionErrorLearner()
        learner.record_failure("str_replace_editor", "[ERROR type=match] No match found for the given old_string in target file /src/app.py", 1)
        learner.record_failure("str_replace_editor", "[ERROR type=match] No match found for the given old_string in target file /src/utils.py", 3)
        hints = learner.get_hypotheses()
        assert len(hints) >= 1
        assert "LEARNED" in hints[0]
        assert "str_replace_editor" in hints[0]

    def test_recovery_map_lookup(self):
        learner = SessionErrorLearner()
        learner.record_failure("str_replace_editor", "[ERROR type=match] No match found for the given old_string in target file /src/app.py", 1)
        learner.record_failure("str_replace_editor", "[ERROR type=match] No match found for the given old_string in target file /src/utils.py", 3)
        hints = learner.get_hypotheses()
        assert any("view_file" in h or "structure_editor" in h for h in hints)

    def test_success_resolves_hypothesis(self):
        learner = SessionErrorLearner()
        learner.record_failure("cmd_run", "[ERROR] not found", 1)
        learner.record_failure("cmd_run", "[ERROR] not found", 2)
        # Before success — hint should be present
        assert len(learner.get_hypotheses()) >= 1
        # Record success — resolves the hypothesis
        learner.record_success("cmd_run", 4)
        hints = learner.get_hypotheses()
        assert not any("cmd_run" in h and "failed" in h.lower() for h in hints)

    def test_max_hints_cap(self):
        learner = SessionErrorLearner()
        # Create failures for multiple tools
        for tool in ["tool_a", "tool_b", "tool_c", "tool_d"]:
            learner.record_failure(tool, "[ERROR] something broke", 1)
            learner.record_failure(tool, "[ERROR] something broke again", 2)
        hints = learner.get_hypotheses(max_hints=3)
        assert len(hints) <= 3

    def test_env_hypothesis_on_cmd_failures(self):
        learner = SessionErrorLearner()
        learner.record_failure("cmd_run", "[ERROR] not found", 1)
        learner.record_failure("bash", "[ERROR] permission denied", 2)
        learner.record_failure("cmd_run", "[ERROR] timeout", 3)
        hints = learner.get_hypotheses()
        assert any("environment" in h.lower() for h in hints)

    def test_multi_tool_same_file_hint(self):
        learner = SessionErrorLearner()
        learner.record_failure(
            "str_replace_editor", "[ERROR] not found /src/app.py", 1
        )
        learner.record_failure(
            "structure_editor", "[ERROR] cannot read /src/app.py", 2
        )
        hints = learner.get_hypotheses()
        assert any("/src/app.py" in h for h in hints)


class TestScanToolResultsForLearning:
    def test_records_failures_from_tool_messages(self):
        planner = _make_planner()
        planner._error_learner = SessionErrorLearner()
        messages = [
            {"role": "user", "content": "fix it"},
            {
                "role": "tool",
                "tool_call_id": "tc_1",
                "name": "str_replace_editor",
                "content": "[ERROR type=match]\nNo match found\n[Error occurred]",
                "forge_tool_ok": False,
            },
            {
                "role": "tool",
                "tool_call_id": "tc_2",
                "name": "str_replace_editor",
                "content": "[ERROR type=match]\nNo match found\n[Error occurred]",
                "forge_tool_ok": False,
            },
        ]
        planner._scan_tool_results_for_learning(messages)
        assert len(planner._error_learner._failures) == 2

    def test_does_not_double_count(self):
        planner = _make_planner()
        planner._error_learner = SessionErrorLearner()
        messages = [
            {
                "role": "tool",
                "tool_call_id": "tc_1",
                "name": "cmd_run",
                "content": "[ERROR] not found",
                "forge_tool_ok": False,
            },
        ]
        planner._scan_tool_results_for_learning(messages)
        planner._scan_tool_results_for_learning(messages)
        assert len(planner._error_learner._failures) == 1

    def test_records_success(self):
        planner = _make_planner()
        planner._error_learner = SessionErrorLearner()
        # Pre-record failures so success can resolve
        planner._error_learner.record_failure("cmd_run", "[ERROR] fail", 0)
        planner._error_learner.record_failure("cmd_run", "[ERROR] fail", 1)
        messages = [
            {
                "role": "tool",
                "tool_call_id": "tc_ok",
                "name": "cmd_run",
                "content": "Command executed successfully.",
                "forge_tool_ok": True,
            },
        ]
        planner._scan_tool_results_for_learning(messages)
        assert "repeated:cmd_run" in planner._error_learner._resolved

    def test_skips_non_tool_messages(self):
        planner = _make_planner()
        planner._error_learner = SessionErrorLearner()
        messages = [
            {"role": "user", "content": "[ERROR] this is user text"},
            {"role": "assistant", "content": "[ERROR] assistant said error"},
        ]
        planner._scan_tool_results_for_learning(messages)
        assert len(planner._error_learner._failures) == 0

    def test_forge_tool_ok_false_without_error_substring(self):
        planner = _make_planner()
        planner._error_learner = SessionErrorLearner()
        messages = [
            {
                "role": "tool",
                "tool_call_id": "tc_x",
                "name": "noop",
                "content": "benign output",
                "forge_tool_ok": False,
            },
        ]
        planner._scan_tool_results_for_learning(messages)
        assert len(planner._error_learner._failures) == 1

    def test_forge_tool_ok_true_ignores_error_word_in_content(self):
        planner = _make_planner()
        planner._error_learner = SessionErrorLearner()
        messages = [
            {
                "role": "tool",
                "tool_call_id": "tc_y",
                "name": "noop",
                "content": "logged an error handler change",
                "forge_tool_ok": True,
            },
        ]
        planner._scan_tool_results_for_learning(messages)
        assert len(planner._error_learner._failures) == 0

    def test_untyped_tool_message_is_ignored_for_learning(self):
        planner = _make_planner()
        planner._error_learner = SessionErrorLearner()
        messages = [
            {
                "role": "tool",
                "tool_call_id": "tc_untyped",
                "name": "ext_tool",
                "content": "[ERROR] looked scary but had no typed status",
            },
        ]
        planner._scan_tool_results_for_learning(messages)
        assert len(planner._error_learner._failures) == 0


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


class TestBuildBehavioralHintsWithLearner:
    def test_learned_hints_included(self):
        planner = _make_planner()
        planner._error_learner = SessionErrorLearner()
        planner._error_learner.record_failure("str_replace_editor", "[ERROR] no match", 1)
        planner._error_learner.record_failure("str_replace_editor", "[ERROR] no match", 3)
        planner._str_replace_count = 0
        hints = BehavioralHintsBuilder(planner._error_learner)._build_behavioral_hints({}, 0, False, planner._str_replace_count)
        assert any("LEARNED" in h for h in hints)

    def test_total_hints_capped_at_five(self):
        planner = _make_planner()
        planner._error_learner = SessionErrorLearner()
        # Create lots of failures
        for tool in ["t1", "t2", "t3", "t4", "t5"]:
            planner._error_learner.record_failure(tool, "[ERROR] fail", 1)
            planner._error_learner.record_failure(tool, "[ERROR] fail", 2)
        planner._str_replace_count = 5
        # Also trigger static hints
        hints = BehavioralHintsBuilder(planner._error_learner)._build_behavioral_hints({"a.py": 4, "b.py": 3}, 4, False, planner._str_replace_count)
        assert len(hints) <= 5
