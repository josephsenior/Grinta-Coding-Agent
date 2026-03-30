"""Tests for backend/execution/utils/tenacity_stop.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.execution.utils.tenacity_stop import stop_if_should_exit


class TestStopIfShouldExit:
    # ── Inheritance ─────────────────────────────────────────────────

    def test_is_stop_base_subclass(self) -> None:
        from tenacity.stop import stop_base
        assert issubclass(stop_if_should_exit, stop_base)

    def test_can_be_instantiated(self) -> None:
        stop = stop_if_should_exit()
        assert stop is not None

    # ── __call__ returns False when NOT exiting ──────────────────────

    def test_returns_false_when_should_not_exit(self) -> None:
        stop = stop_if_should_exit()
        retry_state = MagicMock()
        with patch("backend.execution.utils.tenacity_stop.should_exit", return_value=False):
            result = stop(retry_state)
        assert result is False

    # ── __call__ returns True when exiting ───────────────────────────

    def test_returns_true_when_should_exit(self) -> None:
        stop = stop_if_should_exit()
        retry_state = MagicMock()
        with patch("backend.execution.utils.tenacity_stop.should_exit", return_value=True):
            result = stop(retry_state)
        assert result is True

    # ── retry_state is passed but ignored ───────────────────────────

    def test_retry_state_not_used(self) -> None:
        stop = stop_if_should_exit()
        with patch("backend.execution.utils.tenacity_stop.should_exit", return_value=False):
            # passing None should still work - retry_state is unused
            result = stop(None)  # type: ignore[arg-type]
        assert result is False

    # ── Multiple calls ───────────────────────────────────────────────

    def test_consistent_results_across_calls(self) -> None:
        stop = stop_if_should_exit()
        retry_state = MagicMock()
        with patch("backend.execution.utils.tenacity_stop.should_exit", return_value=False):
            assert stop(retry_state) is False
            assert stop(retry_state) is False

    def test_respects_changing_should_exit(self) -> None:
        stop = stop_if_should_exit()
        retry_state = MagicMock()
        with patch("backend.execution.utils.tenacity_stop.should_exit", return_value=False):
            assert stop(retry_state) is False
        with patch("backend.execution.utils.tenacity_stop.should_exit", return_value=True):
            assert stop(retry_state) is True
