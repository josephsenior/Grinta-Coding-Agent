"""Tests for structured reflection with session metrics."""

from __future__ import annotations

from unittest.mock import MagicMock


from backend.engines.orchestrator.orchestrator import Orchestrator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(turn: int = 10, max_turn: int = 30, errors: int = 0):
    """Create a minimal mock State for reflection testing."""
    state = MagicMock()

    # Iteration flag
    iter_flag = MagicMock()
    iter_flag.current_value = turn
    iter_flag.max_value = max_turn
    state.iteration_flag = iter_flag

    # Metrics
    metrics = MagicMock()
    atu = MagicMock()
    atu.prompt_tokens = 40_000
    atu.context_window = 100_000
    metrics.accumulated_token_usage = atu
    metrics.accumulated_cost = 0.0235
    state.metrics = metrics

    # History
    history: list = []
    for _ in range(errors):
        err = MagicMock()
        type(err).__name__ = "ErrorObservation"
        history.append(err)
    # Add a user message for original request
    user_msg = MagicMock()
    user_msg.source = "user"
    user_msg.content = "Fix the authentication bug and add unit tests"
    type(user_msg).__name__ = "MessageAction"
    history.insert(0, user_msg)
    state.history = history

    return state


# ---------------------------------------------------------------------------
# _maybe_inject_reflection
# ---------------------------------------------------------------------------


class TestStructuredReflection:
    """Test the enriched _maybe_inject_reflection method."""

    def _create_orchestrator_with_reflection(self, interval: int = 1):
        """Create an Orchestrator mock with reflection enabled."""
        # We can't easily instantiate a full Orchestrator, so we test
        # the reflection method in isolation by calling it directly.
        # Import needed for the method
        from backend.engines.orchestrator.file_verification_guard import (
            FileVerificationGuard,
        )

        class MockOrchestrator:
            """Minimal mock to test _maybe_inject_reflection."""

            def __init__(self):
                self._reflection_interval = interval
                self._steps_since_reflection = interval  # trigger on first call
                self.anti_hallucination = FileVerificationGuard()
                self.memory_manager = MagicMock()

            _maybe_inject_reflection = Orchestrator._maybe_inject_reflection
            _build_reflection_data_parts = Orchestrator._build_reflection_data_parts
            _count_recent_errors = Orchestrator._count_recent_errors

        return MockOrchestrator()

    def test_reflection_returns_none_before_interval(self):
        orch = self._create_orchestrator_with_reflection(interval=5)
        orch._steps_since_reflection = 3  # Not yet at interval
        result = orch._maybe_inject_reflection(None)
        assert result is None

    def test_reflection_returns_action_at_interval(self):
        orch = self._create_orchestrator_with_reflection(interval=5)
        orch._steps_since_reflection = 5  # At interval
        result = orch._maybe_inject_reflection(None)
        assert result is not None

    def test_reflection_includes_turn_count(self):
        orch = self._create_orchestrator_with_reflection(interval=1)
        state = _make_state(turn=10, max_turn=30)
        result = orch._maybe_inject_reflection(state)
        assert result is not None
        assert "Turn 10" in result.thought

    def test_reflection_includes_budget_percentage(self):
        orch = self._create_orchestrator_with_reflection(interval=1)
        state = _make_state(turn=10, max_turn=30)
        result = orch._maybe_inject_reflection(state)
        assert result is not None
        assert "33%" in result.thought  # 10/30 = 33%

    def test_reflection_includes_token_usage(self):
        orch = self._create_orchestrator_with_reflection(interval=1)
        state = _make_state(turn=5)
        result = orch._maybe_inject_reflection(state)
        assert result is not None
        assert "40%" in result.thought  # 40000/100000 = 40%

    def test_reflection_includes_cost(self):
        orch = self._create_orchestrator_with_reflection(interval=1)
        state = _make_state(turn=5)
        result = orch._maybe_inject_reflection(state)
        assert result is not None
        assert "$0.0235" in result.thought

    def test_reflection_includes_error_count(self):
        orch = self._create_orchestrator_with_reflection(interval=1)
        state = _make_state(turn=5, errors=3)
        result = orch._maybe_inject_reflection(state)
        assert result is not None
        assert "Errors encountered: 3" in result.thought

    def test_reflection_includes_modified_files(self):
        orch = self._create_orchestrator_with_reflection(interval=1)
        orch.anti_hallucination.record_file_modification("src/auth.py", turn=2)
        orch.anti_hallucination.record_file_modification("tests/test_auth.py", turn=3)
        state = _make_state(turn=5)
        result = orch._maybe_inject_reflection(state)
        assert result is not None
        assert "src/auth.py" in result.thought

    def test_reflection_resets_counter(self):
        orch = self._create_orchestrator_with_reflection(interval=5)
        orch._steps_since_reflection = 5
        orch._maybe_inject_reflection(None)
        assert orch._steps_since_reflection == 0

    def test_disabled_reflection_returns_none(self):
        orch = self._create_orchestrator_with_reflection(interval=0)
        result = orch._maybe_inject_reflection(None)
        assert result is None

    def test_negative_interval_returns_none(self):
        orch = self._create_orchestrator_with_reflection(interval=-1)
        result = orch._maybe_inject_reflection(None)
        assert result is None
