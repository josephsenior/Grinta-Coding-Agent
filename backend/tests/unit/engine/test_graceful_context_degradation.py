"""Behavioural tests for Orchestrator._attempt_graceful_context_degradation.

Tests verify the in-place mutation strategy: large CmdOutputObservation entries
are shrunk to head+tail, old ErrorObservation entries beyond the last 5 are
replaced by a short sentinel, and the method returns None when nothing was
shrunk (so the caller raises instead of infinite-looping).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from backend.engine.orchestrator import Orchestrator
from backend.ledger.observation import CmdOutputObservation, ErrorObservation

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_orchestrator() -> Orchestrator:
    """Return a bare Orchestrator with only the attributes the method touches."""
    orch = object.__new__(Orchestrator)
    memory_manager = MagicMock()
    setattr(memory_manager, 'condense_history', MagicMock(return_value=MagicMock()))
    orch.memory_manager = memory_manager
    setattr(orch, '_execute_llm_step_async', AsyncMock(return_value=MagicMock()))
    return orch


def _make_state(history: list) -> MagicMock:
    state = MagicMock()
    state.history = list(history)
    return state


def _make_large_cmd_obs(size: int = 3000) -> CmdOutputObservation:
    obs = CmdOutputObservation.__new__(CmdOutputObservation)
    obs.content = 'X' * size
    return obs


def _make_error_obs(msg: str = 'error') -> ErrorObservation:
    obs = ErrorObservation.__new__(ErrorObservation)
    obs.content = msg
    return obs


# ---------------------------------------------------------------------------
# CmdOutputObservation shrinking
# ---------------------------------------------------------------------------


class TestCmdOutputShrinking:
    def test_large_output_is_truncated(self):
        orch = _make_orchestrator()
        obs = _make_large_cmd_obs(3000)
        state = _make_state([obs])

        asyncio.get_event_loop().run_until_complete(
            orch._attempt_graceful_context_degradation(state)
        )

        # Content must be shorter than the original.
        assert len(obs.content) < 3000

    def test_truncated_content_has_sentinel_marker(self):
        orch = _make_orchestrator()
        obs = _make_large_cmd_obs(3000)
        state = _make_state([obs])

        asyncio.get_event_loop().run_until_complete(
            orch._attempt_graceful_context_degradation(state)
        )

        assert 'graceful-degradation truncated' in obs.content

    def test_head_and_tail_preserved(self):
        orch = _make_orchestrator()
        head_marker = 'HEAD_MARKER'
        tail_marker = 'TAIL_MARKER'
        padding = 'M' * 2000
        obs = _make_large_cmd_obs(0)
        obs.content = head_marker + padding + tail_marker

        state = _make_state([obs])
        asyncio.get_event_loop().run_until_complete(
            orch._attempt_graceful_context_degradation(state)
        )

        assert head_marker in obs.content
        assert tail_marker in obs.content

    def test_small_output_untouched(self):
        """Outputs shorter than 2000 chars must not be modified."""
        orch = _make_orchestrator()
        obs = _make_large_cmd_obs(500)
        original = obs.content
        state = _make_state([obs])

        asyncio.get_event_loop().run_until_complete(
            orch._attempt_graceful_context_degradation(state)
        )

        assert obs.content == original

    def test_returns_none_when_nothing_to_shrink(self):
        """If no observations needed shrinking, method returns None."""
        orch = _make_orchestrator()
        obs = _make_large_cmd_obs(100)  # too small to trigger
        state = _make_state([obs])

        result = asyncio.get_event_loop().run_until_complete(
            orch._attempt_graceful_context_degradation(state)
        )

        assert result is None


# ---------------------------------------------------------------------------
# ErrorObservation thinning
# ---------------------------------------------------------------------------


class TestErrorObservationThinning:
    def test_old_errors_beyond_last_5_are_replaced(self):
        orch = _make_orchestrator()
        errors = [_make_error_obs(f'error {i}') for i in range(8)]
        state = _make_state(errors)

        asyncio.get_event_loop().run_until_complete(
            orch._attempt_graceful_context_degradation(state)
        )

        # The first 3 (indices 0-2) should have been replaced by a sentinel.
        for i in range(3):
            assert 'graceful-degradation' in errors[i].content

    def test_last_5_errors_preserved(self):
        orch = _make_orchestrator()
        errors = [_make_error_obs(f'important_error_{i}') for i in range(8)]
        state = _make_state(errors)

        asyncio.get_event_loop().run_until_complete(
            orch._attempt_graceful_context_degradation(state)
        )

        # The last 5 (indices 3-7) must keep their original content.
        for i in range(3, 8):
            assert 'important_error_' in errors[i].content

    def test_five_or_fewer_errors_untouched(self):
        orch = _make_orchestrator()
        errors = [_make_error_obs(f'err_{i}') for i in range(5)]
        originals = [e.content for e in errors]
        state = _make_state(errors)

        asyncio.get_event_loop().run_until_complete(
            orch._attempt_graceful_context_degradation(state)
        )

        for orig, obs in zip(originals, errors, strict=False):
            assert obs.content == orig

    def test_history_length_unchanged(self):
        """In-place replacement must never change history length."""
        orch = _make_orchestrator()
        errors = [_make_error_obs(f'e{i}') for i in range(10)]
        state = _make_state(errors)

        asyncio.get_event_loop().run_until_complete(
            orch._attempt_graceful_context_degradation(state)
        )

        assert len(state.history) == 10


# ---------------------------------------------------------------------------
# Empty / degenerate states
# ---------------------------------------------------------------------------


class TestDegenerateState:
    def test_none_history_returns_none(self):
        orch = _make_orchestrator()
        state = MagicMock()
        state.history = None

        result = asyncio.get_event_loop().run_until_complete(
            orch._attempt_graceful_context_degradation(state)
        )

        assert result is None

    def test_empty_history_returns_none(self):
        orch = _make_orchestrator()
        state = _make_state([])

        result = asyncio.get_event_loop().run_until_complete(
            orch._attempt_graceful_context_degradation(state)
        )

        assert result is None
