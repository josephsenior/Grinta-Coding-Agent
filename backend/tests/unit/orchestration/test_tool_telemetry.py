"""Unit tests for backend.orchestration.tool_telemetry — metrics recording."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

from backend.orchestration.tool_pipeline import ToolInvocationContext
from backend.orchestration.tool_telemetry import ToolTelemetry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_telemetry() -> ToolTelemetry:
    """Build a fresh instance (not the singleton) for isolated tests."""
    t = ToolTelemetry.__new__(ToolTelemetry)
    t._recent_events = []
    import threading

    t._recent_lock = threading.Lock()
    t._invocations = None
    t._latency = None
    return t


def _make_ctx(action_name: str = 'CmdRunAction') -> ToolInvocationContext:
    action = MagicMock()
    type(action).__name__ = action_name
    action.action = action_name
    return ToolInvocationContext(
        controller=MagicMock(),
        action=action,
        state=MagicMock(),
        metadata={},
    )


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_get_instance_returns_same(self):
        # Reset for clean test
        ToolTelemetry._instance = None
        a = ToolTelemetry.get_instance()
        b = ToolTelemetry.get_instance()
        assert a is b
        # Cleanup
        ToolTelemetry._instance = None


# ---------------------------------------------------------------------------
# on_plan / on_execute / on_observe lifecycle
# ---------------------------------------------------------------------------


class TestLifecycleHooks:
    def test_on_plan_sets_start_time(self):
        t = _fresh_telemetry()
        ctx = _make_ctx()
        t.on_plan(ctx)
        tel = ctx.metadata['telemetry']
        assert 'start_time' in tel
        assert tel['tool_name'] == 'CmdRunAction'

    def test_on_execute_sets_execute_time(self):
        t = _fresh_telemetry()
        ctx = _make_ctx()
        t.on_plan(ctx)
        t.on_execute(ctx)
        assert 'execute_time' in ctx.metadata['telemetry']

    def test_on_observe_records_event(self):
        t = _fresh_telemetry()
        ctx = _make_ctx()
        t.on_plan(ctx)
        obs = MagicMock()
        obs.__class__ = type('CmdOutputObservation', (), {})
        t.on_observe(ctx, obs)
        events = t.recent_events()
        assert len(events) == 1
        assert events[0]['tool'] == 'CmdRunAction'
        assert events[0]['outcome'] == 'success'

    def test_on_observe_error_observation(self):
        t = _fresh_telemetry()
        ctx = _make_ctx()
        t.on_plan(ctx)
        from backend.ledger.observation import ErrorObservation

        obs = ErrorObservation(content='fail')
        t.on_observe(ctx, obs)
        events = t.recent_events()
        assert events[0]['outcome'] == 'failure'

    def test_on_observe_none_observation(self):
        t = _fresh_telemetry()
        ctx = _make_ctx()
        t.on_plan(ctx)
        t.on_observe(ctx, None)
        events = t.recent_events()
        assert events[0]['outcome'] == 'success'

    def test_on_blocked(self):
        t = _fresh_telemetry()
        ctx = _make_ctx()
        t.on_plan(ctx)
        t.on_blocked(ctx, reason='security')
        events = t.recent_events()
        assert len(events) == 1
        assert 'blocked' in events[0]['outcome']


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


class TestInternalHelpers:
    def test_determine_outcome_success(self):
        t = _fresh_telemetry()
        assert t._determine_outcome(None) == 'success'
        assert t._determine_outcome(MagicMock()) == 'success'

    def test_determine_outcome_failure(self):
        from backend.ledger.observation import ErrorObservation

        t = _fresh_telemetry()
        obs = ErrorObservation(content='err')
        assert t._determine_outcome(obs) == 'failure'

    def test_elapsed_since_none(self):
        t = _fresh_telemetry()
        assert t._elapsed_since(None) == 0.0

    def test_elapsed_since_with_start(self):
        t = _fresh_telemetry()
        tel = {'start_time': time.monotonic() - 1.0}
        elapsed = t._elapsed_since(tel)
        assert elapsed >= 0.9

    def test_record_ring_buffer_limit(self):
        t = _fresh_telemetry()
        for i in range(250):
            t._record(f'tool_{i}', 'success', 0.1)
        assert len(t.recent_events()) == 200

    def test_reset_for_test(self):
        t = _fresh_telemetry()
        t._record('tool', 'success', 0.1)
        assert len(t.recent_events()) == 1
        t.reset_for_test()
        assert len(t.recent_events()) == 0


# ---------------------------------------------------------------------------
# action_to_dict static helper
# ---------------------------------------------------------------------------


class TestActionToDict:
    def test_basic_action(self):
        action = MagicMock()
        action.action = 'run'
        action.command = 'echo hello'
        action.runnable = True
        action.path = None
        action.content = None
        action.code = None
        action.message = None
        action.thought = None
        d = ToolTelemetry.action_to_dict(action)
        assert d['action_type'] == 'run'
        assert d['command'] == 'echo hello'
        assert d['runnable'] is True

    def test_action_without_action_attr(self):
        action = MagicMock(spec=[])
        type(action).__name__ = 'CustomAction'
        d = ToolTelemetry.action_to_dict(action)
        assert d['action_type'] == 'CustomAction'


# ---------------------------------------------------------------------------
# Concurrent safety
# ---------------------------------------------------------------------------


class TestConcurrentSafety:
    def test_thread_safety_record(self):
        """Multiple threads recording should not crash."""
        import threading

        t = _fresh_telemetry()
        errors = []

        def record_many():
            try:
                for i in range(50):
                    t._record('tool', 'success', 0.01)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=record_many) for _ in range(4)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()

        assert not errors
        assert len(t.recent_events()) <= 200
