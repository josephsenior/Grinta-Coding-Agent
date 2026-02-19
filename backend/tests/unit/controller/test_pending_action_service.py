"""Tests for backend.controller.services.pending_action_service."""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


from backend.controller.services.pending_action_service import PendingActionService


def _make_context() -> MagicMock:
    controller = MagicMock()
    controller.event_stream = MagicMock()
    ctx = MagicMock()
    ctx.get_controller.return_value = controller
    return ctx


def _make_action(action_id: int = 1) -> SimpleNamespace:
    return SimpleNamespace(id=action_id)


# ── constructor ──────────────────────────────────────────────────────


class TestPendingActionServiceInit:
    def test_initial_state_is_none(self):
        svc = PendingActionService(_make_context(), timeout=30.0)
        assert svc.get() is None
        assert svc.info() is None


# ── set / get ────────────────────────────────────────────────────────


class TestSetGet:
    def test_set_and_get_returns_action(self):
        svc = PendingActionService(_make_context(), timeout=300.0)
        action = _make_action()
        svc.set(action)
        assert svc.get() is action

    def test_set_none_clears_pending(self):
        svc = PendingActionService(_make_context(), timeout=300.0)
        svc.set(_make_action())
        svc.set(None)
        assert svc.get() is None

    def test_set_none_when_empty_no_error(self):
        svc = PendingActionService(_make_context(), timeout=300.0)
        svc.set(None)  # should not raise
        assert svc.get() is None

    def test_info_returns_tuple(self):
        svc = PendingActionService(_make_context(), timeout=300.0)
        action = _make_action()
        svc.set(action)
        info = svc.info()
        assert info is not None
        stored_action, ts = info
        assert stored_action is action
        assert isinstance(ts, float)

    def test_overwrite_pending_action(self):
        svc = PendingActionService(_make_context(), timeout=300.0)
        a1 = _make_action(1)
        a2 = _make_action(2)
        svc.set(a1)
        svc.set(a2)
        assert svc.get() is a2


# ── timeout ──────────────────────────────────────────────────────────


class TestTimeout:
    def test_get_returns_none_after_timeout(self):
        ctx = _make_context()
        svc = PendingActionService(ctx, timeout=5.0)
        action = _make_action()
        svc.set(action)
        # Manually backdate the stored timestamp so elapsed > timeout
        svc._pending = (action, time.time() - 10.0)
        result = svc.get()
        assert result is None

    def test_timeout_emits_error_observation(self):
        ctx = _make_context()
        controller = ctx.get_controller()
        svc = PendingActionService(ctx, timeout=5.0)
        action = _make_action(42)
        svc.set(action)
        svc._pending = (action, time.time() - 10.0)
        svc.get()  # triggers timeout
        controller.event_stream.add_event.assert_called_once()
        obs = controller.event_stream.add_event.call_args[0][0]
        assert "timed out" in obs.content.lower()

    def test_timeout_sets_cause_from_action_id(self):
        ctx = _make_context()
        controller = ctx.get_controller()
        svc = PendingActionService(ctx, timeout=5.0)
        action = _make_action(77)
        svc.set(action)
        svc._pending = (action, time.time() - 10.0)
        svc.get()
        obs = controller.event_stream.add_event.call_args[0][0]
        assert obs.cause == 77

    def test_timeout_cause_none_for_non_int_id(self):
        ctx = _make_context()
        controller = ctx.get_controller()
        svc = PendingActionService(ctx, timeout=5.0)
        action = SimpleNamespace(id="not-an-int")
        svc.set(action)
        svc._pending = (action, time.time() - 10.0)
        svc.get()
        obs = controller.event_stream.add_event.call_args[0][0]
        assert obs.cause is None


# ── slow pending logging ─────────────────────────────────────────────


class TestSlowPendingLogging:
    def test_slow_pending_logs_at_60s(self):
        """Actions pending > 60s log at 30s intervals."""
        ctx = _make_context()
        controller = ctx.get_controller()
        svc = PendingActionService(ctx, timeout=600.0)  # long timeout
        action = _make_action()
        svc.set(action)
        # Patch the stored timestamp to 90s ago and make elapsed divisible by 30
        svc._pending = (action, time.time() - 90.0)
        with patch(
            "backend.controller.services.pending_action_service.time"
        ) as mock_time:
            mock_time.time.return_value = svc._pending[1] + 90.0
            svc.get()
        # controller.log should have been called for the slow warning
        calls = [c for c in controller.log.call_args_list if "active for" in str(c)]
        assert calls
