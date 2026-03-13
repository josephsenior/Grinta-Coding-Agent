"""Tests for backend.engines.orchestrator.planner — pure regex and message helpers."""

from __future__ import annotations


from backend.engines.orchestrator.planner import (
    OrchestratorPlanner,
    SessionErrorLearner,
)


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
            },
            {
                "role": "tool",
                "tool_call_id": "tc_2",
                "name": "str_replace_editor",
                "content": "[ERROR type=match]\nNo match found\n[Error occurred]",
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


class TestBuildBehavioralHintsWithLearner:
    def test_learned_hints_included(self):
        planner = _make_planner()
        planner._error_learner = SessionErrorLearner()
        planner._error_learner.record_failure("str_replace_editor", "[ERROR] no match", 1)
        planner._error_learner.record_failure("str_replace_editor", "[ERROR] no match", 3)
        planner._str_replace_count = 0
        hints = planner._build_behavioral_hints({}, 0, False)
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
        hints = planner._build_behavioral_hints(
            {"a.py": 4, "b.py": 3}, 4, False
        )
        assert len(hints) <= 5
