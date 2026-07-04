"""Unit tests for backend.orchestration.telemetry.tool_telemetry — metrics recording."""

from __future__ import annotations

import threading
import time
from typing import Any, cast
from unittest.mock import MagicMock, patch

from backend.ledger.action.commands import CmdRunAction
from backend.ledger.observation.commands import CmdOutputObservation
from backend.orchestration.telemetry.tool_telemetry import ToolTelemetry
from backend.orchestration.tool_pipeline import ToolInvocationContext

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

    def test_get_instance_thread_safe(self):
        instances = []

        def get_instance():
            instances.append(ToolTelemetry.get_instance())

        threads = [threading.Thread(target=get_instance) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len({id(inst) for inst in instances}) == 1


# ---------------------------------------------------------------------------
# Initialization (from test_tool_telemetry2)
# ---------------------------------------------------------------------------


class TestToolTelemetryInit:
    def test_init_sets_recent_events(self):
        tt = ToolTelemetry()
        assert hasattr(tt, '_recent_events')
        assert isinstance(tt._recent_events, list)

    def test_init_sets_lock(self):
        tt = ToolTelemetry()
        assert hasattr(tt, '_recent_lock')
        assert tt._recent_lock is not None

    def test_prometheus_metrics_available(self):
        tt = ToolTelemetry()
        assert hasattr(tt, '_invocations')
        assert hasattr(tt, '_latency')

    def test_setup_prometheus_uses_app_metric_names(self):
        counter = MagicMock()
        histogram = MagicMock()
        fake_prometheus = MagicMock()
        fake_prometheus.Counter = counter
        fake_prometheus.Histogram = histogram
        fake_prometheus.REGISTRY = MagicMock(_names_to_collectors={})

        ToolTelemetry._shared_invocations = None
        ToolTelemetry._shared_latency = None
        try:
            with patch(
                'backend.orchestration.telemetry.tool_telemetry.importlib.import_module',
                return_value=fake_prometheus,
            ):
                ToolTelemetry()

            counter.assert_called_once_with(
                'app_tool_invocations_total',
                'Number of tool invocations processed by the agent controller',
                labelnames=('tool', 'outcome'),
            )
            histogram.assert_called_once_with(
                'app_tool_latency_seconds',
                'Duration of tool invocations executed by the agent controller',
                labelnames=('tool', 'outcome'),
                buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, float('inf')),
            )
        finally:
            ToolTelemetry._shared_invocations = None
            ToolTelemetry._shared_latency = None


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

    def test_on_plan_sets_tool_name(self):
        tt = ToolTelemetry()
        ctx = MagicMock()
        ctx.metadata = {}
        ctx.action = CmdRunAction(command='ls')
        cast(Any, ctx.action).action = 'run_command'

        tt.on_plan(ctx)

        assert ctx.metadata['telemetry']['tool_name'] == 'run_command'

    def test_on_plan_converts_action_to_schema(self):
        tt = ToolTelemetry()
        ctx = MagicMock()
        ctx.metadata = {}
        ctx.action = CmdRunAction(command='ls')

        with patch.object(tt, '_action_to_schema', return_value=None):
            tt.on_plan(ctx)
            assert 'telemetry' in ctx.metadata

    def test_on_observe_no_telemetry_in_metadata(self):
        tt = ToolTelemetry()
        ctx = MagicMock()
        ctx.metadata = {}
        obs = CmdOutputObservation(
            command='ls', command_id=1, exit_code=0, content='output'
        )
        tt.on_observe(ctx, obs)

    def test_on_observe_determines_outcome_and_duration(self):
        tt = ToolTelemetry()
        ctx = MagicMock()
        ctx.metadata = {
            'telemetry': {
                'start_time': time.monotonic() - 1.0,
                'tool_name': 'test_tool',
            }
        }
        ctx.action = MagicMock()
        ctx.action.action = 'test_action'
        obs = CmdOutputObservation(
            command='ls', command_id=1, exit_code=0, content='output'
        )

        with (
            patch.object(tt, '_determine_outcome', return_value='success'),
            patch.object(tt, '_elapsed_since', return_value=1.5),
            patch.object(tt, '_record') as mock_record,
        ):
            tt.on_observe(ctx, obs)
            mock_record.assert_called_once()


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

    def test_record_increments_counter_when_available(self):
        tt = ToolTelemetry()
        mock_counter = MagicMock()
        tt._invocations = mock_counter
        tt._latency = MagicMock()

        tt._record('test_tool', 'success', 1.5)

        mock_counter.labels.assert_called_with(tool='test_tool', outcome='success')

    def test_record_without_prometheus(self):
        tt = ToolTelemetry()
        tt._invocations = None
        tt._latency = None
        tt._record('test_tool', 'success', 1.5)

    def test_record_appends_to_recent_events(self):
        tt = ToolTelemetry()
        tt._record('test_tool', 'success', 1.0)

        assert len(tt._recent_events) == 1
        assert tt._recent_events[0]['tool'] == 'test_tool'


class TestRecentEvents:
    def test_returns_copy_of_events(self):
        tt = ToolTelemetry()
        tt._record('test', 'success', 1.0)

        events = tt.recent_events()
        assert isinstance(events, list)
        assert len(events) == 1

        events.clear()
        assert len(tt._recent_events) == 1


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
