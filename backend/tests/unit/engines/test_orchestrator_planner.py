"""Tests for backend.engines.orchestrator.planner — pure regex and message helpers."""

from __future__ import annotations


from backend.engines.orchestrator.planner import (
    ACTION_PATTERNS,
    QUESTION_PATTERNS,
    OrchestratorPlanner,
)


# We test the static/pure methods by creating a planner with minimal mocks.
def _make_planner():
    """Create a planner with None dependencies for testing pure methods."""
    # The pure methods _is_question, _is_action, _get_last_user_message
    # don't use self._config, self._llm, or self._safety.

    return object.__new__(OrchestratorPlanner)


class TestIsQuestion:
    def test_why(self):
        p = _make_planner()
        assert p._is_question("Why does this fail?") is True

    def test_how_does(self):
        p = _make_planner()
        assert p._is_question("How does the cache work?") is True

    def test_what_is(self):
        p = _make_planner()
        assert p._is_question("What is the purpose of this function?") is True

    def test_explain(self):
        p = _make_planner()
        assert p._is_question("Explain the architecture") is True

    def test_question_mark(self):
        p = _make_planner()
        assert p._is_question("Is this correct?") is True

    def test_not_a_question(self):
        p = _make_planner()
        assert p._is_question("Create a new file") is False

    def test_can_you_explain(self):
        p = _make_planner()
        assert p._is_question("Can you explain this code?") is True

    def test_tell_me(self):
        p = _make_planner()
        assert p._is_question("Tell me about the api") is True


class TestIsAction:
    def test_create(self):
        p = _make_planner()
        assert p._is_action("Create a new file") is True

    def test_fix(self):
        p = _make_planner()
        assert p._is_action("Fix the broken test") is True

    def test_implement(self):
        p = _make_planner()
        assert p._is_action("Implement the login feature") is True

    def test_write(self):
        p = _make_planner()
        assert p._is_action("Write unit tests") is True

    def test_run(self):
        p = _make_planner()
        assert p._is_action("Run the build process") is True

    def test_not_an_action(self):
        p = _make_planner()
        assert p._is_action("Why does this fail?") is False

    def test_install(self):
        p = _make_planner()
        assert p._is_action("Install the dependencies") is True

    def test_delete(self):
        p = _make_planner()
        assert p._is_action("Delete the temp files") is True


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
    def test_question_patterns_not_empty(self):
        assert QUESTION_PATTERNS

    def test_action_patterns_not_empty(self):
        assert ACTION_PATTERNS

    def test_question_patterns_are_regex(self):
        import re

        for p in QUESTION_PATTERNS:
            re.compile(p)  # Should not raise

    def test_action_patterns_are_regex(self):
        import re

        for p in ACTION_PATTERNS:
            re.compile(p)  # Should not raise
