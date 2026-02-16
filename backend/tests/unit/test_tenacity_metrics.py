"""Tests for backend.utils.tenacity_metrics — retry hook factories."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.utils.tenacity_metrics import (
    call_tenacity_hooks,
    tenacity_after_factory,
    tenacity_before_sleep_factory,
)


def _make_retry_state(attempt_number=1, max_attempts=3, outcome=None, stop=None):
    """Build a mock RetryCallState-like object."""
    rs = SimpleNamespace(
        attempt_number=attempt_number,
        outcome=outcome,
        stop=stop or SimpleNamespace(max_attempts=max_attempts),
    )
    return rs


class TestCallTenacityHooks:
    """Tests for safe hook invocation."""

    def test_both_hooks_called(self):
        before = MagicMock()
        after = MagicMock()
        rs = _make_retry_state()
        call_tenacity_hooks(before, after, rs)
        before.assert_called_once_with(rs)
        after.assert_called_once_with(rs)

    def test_none_hooks_are_skipped(self):
        rs = _make_retry_state()
        # Should not raise
        call_tenacity_hooks(None, None, rs)

    def test_before_exception_suppressed(self):
        before = MagicMock(side_effect=RuntimeError("boom"))
        after = MagicMock()
        rs = _make_retry_state()
        # Should not raise
        call_tenacity_hooks(before, after, rs)
        after.assert_called_once_with(rs)

    def test_after_exception_suppressed(self):
        before = MagicMock()
        after = MagicMock(side_effect=RuntimeError("boom"))
        rs = _make_retry_state()
        call_tenacity_hooks(before, after, rs)
        before.assert_called_once_with(rs)


class TestTenacityBeforeSleepFactory:
    """Tests for the before_sleep factory."""

    def test_returns_callable(self):
        hook = tenacity_before_sleep_factory("my_op")
        assert callable(hook)

    @patch("backend.utils.tenacity_metrics._record_metrics_event_runtime")
    def test_hook_records_attempt_event(self, mock_record):
        hook = tenacity_before_sleep_factory("my_op")
        rs = _make_retry_state(attempt_number=2, max_attempts=5)
        hook(rs)
        mock_record.assert_called_once()
        event = mock_record.call_args[0][0]
        assert event["status"] == "attempt"
        assert event["operation"] == "my_op"
        assert event["attempt_index"] == 2
        assert event["max_attempts"] == 5

    @patch("backend.utils.tenacity_metrics._record_metrics_event_runtime")
    def test_hook_with_no_stop_attribute(self, mock_record):
        hook = tenacity_before_sleep_factory("test_op")
        rs = SimpleNamespace(attempt_number=1)  # no 'stop'
        hook(rs)
        mock_record.assert_called_once()
        event = mock_record.call_args[0][0]
        assert event["max_attempts"] is None

    def test_hook_exception_suppressed(self):
        """The hook wraps everything in contextlib.suppress."""
        hook = tenacity_before_sleep_factory("op")
        # Pass something that isn't a proper retry_state — should not raise
        hook("not a retry state")


class TestTenacityAfterFactory:
    """Tests for the after factory."""

    def test_returns_callable(self):
        hook = tenacity_after_factory("my_op")
        assert callable(hook)

    @patch("backend.utils.tenacity_metrics._record_metrics_event_runtime")
    def test_successful_outcome(self, mock_record):
        hook = tenacity_after_factory("my_op")
        outcome = MagicMock()
        outcome.successful.return_value = True
        rs = _make_retry_state(outcome=outcome)
        hook(rs)
        mock_record.assert_called_once()
        event = mock_record.call_args[0][0]
        assert event["status"] == "retry_success"
        assert event["operation"] == "my_op"

    @patch("backend.utils.tenacity_metrics._record_metrics_event_runtime")
    def test_failure_at_max_attempts(self, mock_record):
        hook = tenacity_after_factory("my_op")
        outcome = MagicMock()
        outcome.successful.return_value = False
        rs = _make_retry_state(attempt_number=3, max_attempts=3, outcome=outcome)
        hook(rs)
        # Should record retry_failure since attempt_number >= max_attempts
        assert mock_record.called
        event = mock_record.call_args[0][0]
        assert event["status"] == "retry_failure"
        assert event["attempt_index"] == 3
        assert event["max_attempts"] == 3

    @patch("backend.utils.tenacity_metrics._record_metrics_event_runtime")
    def test_no_event_when_not_at_max(self, mock_record):
        hook = tenacity_after_factory("my_op")
        outcome = MagicMock()
        outcome.successful.return_value = False
        rs = _make_retry_state(attempt_number=1, max_attempts=3, outcome=outcome)
        hook(rs)
        # Not at max attempts, no failure event
        mock_record.assert_not_called()

    def test_exception_in_hook_suppressed(self):
        hook = tenacity_after_factory("op")
        # outcome.successful() raises
        outcome = MagicMock()
        outcome.successful.side_effect = RuntimeError("boom")
        rs = _make_retry_state(attempt_number=1, max_attempts=3, outcome=outcome)
        # Should not raise
        hook(rs)

    @patch("backend.utils.tenacity_metrics._record_metrics_event_runtime")
    def test_no_outcome_attribute(self, mock_record):
        hook = tenacity_after_factory("op")
        rs = SimpleNamespace(attempt_number=3)  # no 'outcome', no 'stop'
        hook(rs)
        # Should not crash; outcome is None → not successful → check max attempts
        # No stop attr → max_attempts is None → isinstance check fails
        mock_record.assert_not_called()
