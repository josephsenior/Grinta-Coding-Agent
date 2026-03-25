"""Unit tests for backend.controller.stuck — StuckDetector."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from backend.controller.stuck import StuckDetector
from backend.controller.stuck_patterns import (
    eq_no_pid,
    is_stuck_monologue,
    is_stuck_repeating_action_error,
    is_stuck_repeating_action_observation,
)
from backend.events.action.commands import CmdRunAction
from backend.events.action.empty import NullAction
from backend.events.action.message import MessageAction
from backend.events.event import EventSource
from backend.events.observation.agent import AgentCondensationObservation
from backend.events.observation.commands import CmdOutputObservation
from backend.events.observation.empty import NullObservation
from backend.events.observation.error import ErrorObservation


# ---------------------------------------------------------------------------
# Helpers for building mock state / events
# ---------------------------------------------------------------------------


def _state(history: list) -> Any:
    """Build a minimal State-like object."""
    return SimpleNamespace(history=history)


def _msg(content: str, source: str = EventSource.AGENT) -> MessageAction:
    m = MessageAction(content=content)
    m._source = source
    return m


def _user_msg(content: str = "user says hi") -> MessageAction:
    return _msg(content, EventSource.USER)


def _agent_msg(content: str = "agent reply") -> MessageAction:
    return _msg(content, EventSource.AGENT)


def _cmd(command: str = "ls") -> CmdRunAction:
    return CmdRunAction(command=command)


def _cmd_output(
    command: str = "ls", content: str = "file.txt", exit_code: int = 0
) -> CmdOutputObservation:
    return CmdOutputObservation(content=content, command=command, exit_code=exit_code)


def _error(content: str = "something failed") -> ErrorObservation:
    return ErrorObservation(content=content)


def _null_action() -> NullAction:
    return NullAction()


def _null_obs() -> NullObservation:
    return NullObservation(content="")


def _condensation(content: str = "condensed") -> AgentCondensationObservation:
    return AgentCondensationObservation(content=content)


# ---------------------------------------------------------------------------
# Helpers — internal pure functions
# ---------------------------------------------------------------------------


class TestEquality:
    def test_eq_no_pid_same_cmd(self):
        assert eq_no_pid(_cmd("ls"), _cmd("ls")) is True

    def test_eq_no_pid_different_cmd(self):
        assert eq_no_pid(_cmd("ls"), _cmd("cat foo")) is False

    def test_eq_no_pid_cmd_output(self):
        o1 = _cmd_output("ls", "out", 0)
        o2 = _cmd_output("ls", "out", 0)
        assert eq_no_pid(o1, o2) is True

    def test_eq_no_pid_cmd_output_different_exit(self):
        o1 = _cmd_output("ls", "out", 0)
        o2 = _cmd_output("ls", "out", 1)
        assert eq_no_pid(o1, o2) is False


# ---------------------------------------------------------------------------
# Filter relevant history
# ---------------------------------------------------------------------------


class TestFilterRelevantHistory:
    def test_filters_null_events(self):
        sd = StuckDetector(_state([]))
        history = [_null_action(), _cmd("ls"), _null_obs(), _error()]
        filtered = sd._filter_relevant_history(history)
        assert len(filtered) == 2
        assert isinstance(filtered[0], CmdRunAction)
        assert isinstance(filtered[1], ErrorObservation)

    def test_filters_user_messages(self):
        sd = StuckDetector(_state([]))
        history = [_user_msg(), _cmd("ls"), _agent_msg()]
        filtered = sd._filter_relevant_history(history)
        # user message removed, agent message kept, cmd kept
        assert len(filtered) == 2


# ---------------------------------------------------------------------------
# _is_stuck_repeating_action_observation
# ---------------------------------------------------------------------------


class TestRepeatingActionObservation:
    def test_four_identical_pairs_is_stuck(self):
        sd = StuckDetector(_state([]))
        actions: list[Any] = [_cmd("echo 1")] * 4
        observations: list[Any] = [_cmd_output("echo 1", "1", 0)] * 4
        assert is_stuck_repeating_action_observation(actions, observations) is True

    def test_different_actions_not_stuck(self):
        sd = StuckDetector(_state([]))
        actions: list[Any] = [_cmd("echo 1"), _cmd("echo 2"), _cmd("echo 3"), _cmd("echo 4")]
        observations: list[Any] = [_cmd_output("echo 1", "1", 0)] * 4
        assert is_stuck_repeating_action_observation(actions, observations) is False

    def test_fewer_than_four_not_stuck(self):
        sd = StuckDetector(_state([]))
        actions: list[Any] = [_cmd("echo 1")] * 3
        observations: list[Any] = [_cmd_output("echo 1", "1", 0)] * 3
        assert is_stuck_repeating_action_observation(actions, observations) is False


# ---------------------------------------------------------------------------
# _is_stuck_repeating_action_error
# ---------------------------------------------------------------------------


class TestRepeatingActionError:
    def test_three_same_action_with_errors_is_stuck(self):
        sd = StuckDetector(_state([]))
        actions: list[Any] = [_cmd("bad-cmd")] * 3
        observations: list[Any] = [_error("fail")] * 3
        assert is_stuck_repeating_action_error(actions, observations) is True

    def test_different_actions_with_errors_not_stuck(self):
        sd = StuckDetector(_state([]))
        actions: list[Any] = [_cmd("a"), _cmd("b"), _cmd("c")]
        observations: list[Any] = [_error()] * 3
        assert is_stuck_repeating_action_error(actions, observations) is False

    def test_fewer_than_three_not_stuck(self):
        sd = StuckDetector(_state([]))
        actions: list[Any] = [_cmd("bad")] * 2
        observations: list[Any] = [_error()] * 2
        assert is_stuck_repeating_action_error(actions, observations) is False


# ---------------------------------------------------------------------------
# _is_stuck_monologue
# ---------------------------------------------------------------------------


class TestMonologue:
    def test_three_identical_agent_messages_is_stuck(self):
        sd = StuckDetector(_state([]))
        msg = _agent_msg("I'm stuck")
        filtered: list[Any] = [msg, msg, msg]
        assert is_stuck_monologue(filtered) is True

    def test_three_different_messages_not_stuck(self):
        sd = StuckDetector(_state([]))
        filtered: list[Any] = [_agent_msg("a"), _agent_msg("b"), _agent_msg("c")]
        assert is_stuck_monologue(filtered) is False

    def test_messages_with_observations_between_not_stuck(self):
        sd = StuckDetector(_state([]))
        msg = _agent_msg("x")
        # observation breaks the monologue
        filtered: list[Any] = [msg, _cmd_output("ls", "file"), msg, msg]
        # First and last two are identical but have observation between first and second
        assert is_stuck_monologue(filtered) is False


# ---------------------------------------------------------------------------
# _is_stuck_context_window_error
# ---------------------------------------------------------------------------


class TestContextWindowError:
    def test_ten_consecutive_condensations_is_stuck(self):
        sd = StuckDetector(_state([]))
        events: list[Any] = [_condensation("c")] * 12
        assert sd._is_stuck_context_window_error(events) is True

    def test_condensations_with_actions_between_not_stuck(self):
        sd = StuckDetector(_state([]))
        events: list[Any] = []
        for _ in range(12):
            events.append(_condensation("c"))
            events.append(_cmd("ls"))  # Action breaks consecutiveness
        assert sd._is_stuck_context_window_error(events) is False

    def test_fewer_than_ten_not_stuck(self):
        sd = StuckDetector(_state([]))
        events: list[Any] = [_condensation("c")] * 8
        assert sd._is_stuck_context_window_error(events) is False


# ---------------------------------------------------------------------------
# _is_stuck_token_repetition
# ---------------------------------------------------------------------------


class TestTokenRepetition:
    def test_three_identical_long_messages_is_stuck(self):
        sd = StuckDetector(_state([]))
        msg = _agent_msg("This is a sufficiently long message to trigger repetition")
        events: list[Any] = [msg, msg, msg]
        assert sd._is_stuck_token_repetition(events) is True

    def test_short_messages_not_stuck(self):
        sd = StuckDetector(_state([]))
        msg = _agent_msg("ok")  # <= 10 chars
        events: list[Any] = [msg, msg, msg]
        assert sd._is_stuck_token_repetition(events) is False

    def test_different_messages_not_stuck(self):
        sd = StuckDetector(_state([]))
        events: list[Any] = [
            _agent_msg("This is message A with enough text"),
            _agent_msg("This is message B with enough text"),
            _agent_msg("This is message C with enough text"),
        ]
        assert sd._is_stuck_token_repetition(events) is False

    def test_fewer_than_three_not_stuck(self):
        sd = StuckDetector(_state([]))
        msg = _agent_msg("long enough to score")
        events: list[Any] = [msg, msg]
        assert sd._is_stuck_token_repetition(events) is False


# ---------------------------------------------------------------------------
# Intent classification helpers
# ---------------------------------------------------------------------------


class TestActionIntentClassification:
    def test_categorize_cmd_test(self):
        sd = StuckDetector(_state([]))
        assert sd._categorize_cmd_action("pytest tests/") == "run_test"

    def test_categorize_cmd_inspect(self):
        sd = StuckDetector(_state([]))
        assert sd._categorize_cmd_action("cat file.py") == "inspect_filesystem"

    def test_categorize_cmd_install(self):
        sd = StuckDetector(_state([]))
        assert sd._categorize_cmd_action("pip install flask") == "install_dependency"

    def test_categorize_cmd_execute(self):
        sd = StuckDetector(_state([]))
        assert sd._categorize_cmd_action("python script.py") == "execute_code"

    def test_categorize_cmd_unknown(self):
        sd = StuckDetector(_state([]))
        assert sd._categorize_cmd_action("some-custom-tool") == "other_command"


class TestObservationOutcome:
    def test_error_observation(self):
        sd = StuckDetector(_state([]))
        assert sd._extract_observation_outcome(_error()) == "error"

    def test_cmd_output_success(self):
        sd = StuckDetector(_state([]))
        assert (
            sd._extract_observation_outcome(_cmd_output("ls", "file", 0)) == "success"
        )

    def test_cmd_output_nonzero_exit(self):
        sd = StuckDetector(_state([]))
        assert sd._extract_observation_outcome(_cmd_output("ls", "err", 1)) == "error"

    def test_cmd_output_zero_exit_ignores_prose(self):
        """Exit 0 means success for stuck scoring; do not infer failure from stdout text."""
        sd = StuckDetector(_state([]))
        obs = _cmd_output("ls", "No such file or directory", 0)
        assert sd._extract_observation_outcome(obs) == "success"

    def test_cmd_output_tool_result_not_ok(self):
        sd = StuckDetector(_state([]))
        obs = _cmd_output("ls", "ok", 0)
        obs.tool_result = {"ok": False}
        assert sd._extract_observation_outcome(obs) == "error"


# ---------------------------------------------------------------------------
# Semantic loop helpers
# ---------------------------------------------------------------------------


class TestSemanticLoopHelpers:
    def test_calculate_intent_diversity_all_same(self):
        sd = StuckDetector(_state([]))
        assert sd._calculate_intent_diversity(["run_test"] * 6) == pytest.approx(1 / 6)

    def test_calculate_intent_diversity_all_different(self):
        sd = StuckDetector(_state([]))
        assert sd._calculate_intent_diversity(list("abcdef")) == pytest.approx(1.0)

    def test_calculate_intent_diversity_empty(self):
        sd = StuckDetector(_state([]))
        assert sd._calculate_intent_diversity([]) == 1.0

    def test_calculate_failure_rate_all_failures(self):
        sd = StuckDetector(_state([]))
        assert sd._calculate_failure_rate(["error"] * 6) == pytest.approx(1.0)

    def test_calculate_failure_rate_no_failures(self):
        sd = StuckDetector(_state([]))
        assert sd._calculate_failure_rate(["success"] * 6) == 0.0

    def test_calculate_failure_rate_mixed(self):
        sd = StuckDetector(_state([]))
        rate = sd._calculate_failure_rate(["error", "success", "no_change", "success"])
        assert rate == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Full is_stuck integration
# ---------------------------------------------------------------------------


class TestIsStuck:
    def test_too_few_events_not_stuck(self):
        sd = StuckDetector(_state([_cmd("ls"), _cmd_output("ls")]))
        assert sd.is_stuck() is False

    def test_action_observation_loop_detected(self):
        """4 identical action-observation pairs should trigger stuck."""
        history: list[Any] = []
        for _ in range(4):
            history.append(_cmd("echo hello"))
            history.append(_cmd_output("echo hello", "hello", 0))
        sd = StuckDetector(_state(history))
        assert sd.is_stuck() is True

    def test_healthy_session_not_stuck(self):
        """Varied commands with successful output should not be stuck."""
        history = [
            _cmd("ls"),
            _cmd_output("ls", "file1 file2"),
            _cmd("cat file1"),
            _cmd_output("cat file1", "content here"),
            _cmd("grep pattern file2"),
            _cmd_output("grep pattern file2", "found"),
        ]
        sd = StuckDetector(_state(history))
        assert sd.is_stuck() is False
