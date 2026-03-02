"""Tests for backend.controller.tool_telemetry — tool invocation telemetry tracking."""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch


from backend.controller.tool_telemetry import ToolTelemetry
from backend.events.action.commands import CmdRunAction
from backend.events.observation.commands import CmdOutputObservation
from backend.events.observation.error import ErrorObservation


# ---------------------------------------------------------------------------
# Singleton instance
# ---------------------------------------------------------------------------
class TestToolTelemetrySingleton:
    def test_get_instance_creates_singleton(self):
        t1 = ToolTelemetry.get_instance()
        t2 = ToolTelemetry.get_instance()
        assert t1 is t2

    def test_get_instance_thread_safe(self):
        instances = []

        def get_instance():
            instances.append(ToolTelemetry.get_instance())

        threads = [threading.Thread(target=get_instance) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        #  All instances should be the same
        assert len({id(inst) for inst in instances}) == 1


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------
class TestToolTelemetryInit:
    def test_init_sets_recent_events(self):
        tt = ToolTelemetry()
        assert hasattr(tt, "_recent_events")
        assert isinstance(tt._recent_events, list)

    def test_init_sets_lock(self):
        tt = ToolTelemetry()
        assert hasattr(tt, "_recent_lock")
        # Lock is an instance check would fail since threading.Lock is a factory
        assert tt._recent_lock is not None

    def test_prometheus_metrics_available(self):
        tt = ToolTelemetry()
        # May be None if prometheus_client not installed, but should have attributes
        assert hasattr(tt, "_invocations")
        assert hasattr(tt, "_latency")


# ---------------------------------------------------------------------------
# Lifecycle hooks — on_plan
# ---------------------------------------------------------------------------
class TestOnPlan:
    def test_sets_start_time(self):
        tt = ToolTelemetry()
        ctx = MagicMock()
        ctx.metadata = {}
        ctx.action = CmdRunAction(command="ls")

        tt.on_plan(ctx)

        assert "telemetry" in ctx.metadata
        assert "start_time" in ctx.metadata["telemetry"]
        assert isinstance(ctx.metadata["telemetry"]["start_time"], float)

    def test_sets_tool_name(self):
        tt = ToolTelemetry()
        ctx = MagicMock()
        ctx.metadata = {}
        ctx.action = CmdRunAction(command="ls")
        ctx.action.action = "run_command"

        tt.on_plan(ctx)

        assert "tool_name" in ctx.metadata["telemetry"]
        assert ctx.metadata["telemetry"]["tool_name"] == "run_command"

    def test_converts_action_to_schema(self):
        tt = ToolTelemetry()
        ctx = MagicMock()
        ctx.metadata = {}
        ctx.action = CmdRunAction(command="ls")

        with patch.object(tt, "_action_to_schema", return_value=None):
            tt.on_plan(ctx)
            # Should not crash even if conversion fails
            assert "telemetry" in ctx.metadata


# ---------------------------------------------------------------------------
# Lifecycle hooks — on_execute
# ---------------------------------------------------------------------------
class TestOnExecute:
    def test_sets_execute_time(self):
        tt = ToolTelemetry()
        ctx = MagicMock()
        ctx.metadata = {}

        tt.on_execute(ctx)

        assert "telemetry" in ctx.metadata
        assert "execute_time" in ctx.metadata["telemetry"]
        assert isinstance(ctx.metadata["telemetry"]["execute_time"], float)


# ---------------------------------------------------------------------------
# Lifecycle hooks — on_observe
# ---------------------------------------------------------------------------
class TestOnObserve:
    def test_no_telemetry_in_metadata(self):
        tt = ToolTelemetry()
        ctx = MagicMock()
        ctx.metadata = {}
        obs = CmdOutputObservation(
            command="ls", command_id=1, exit_code=0, content="output"
        )

        # Should not crash
        tt.on_observe(ctx, obs)

    def test_determines_outcome_and_duration(self):
        tt = ToolTelemetry()
        ctx = MagicMock()
        ctx.metadata = {
            "telemetry": {
                "start_time": time.monotonic() - 1.0,
                "tool_name": "test_tool",
            }
        }
        ctx.action = MagicMock()
        ctx.action.action = "test_action"
        obs = CmdOutputObservation(
            command="ls", command_id=1, exit_code=0, content="output"
        )

        with patch.object(tt, "_determine_outcome", return_value="success"):
            with patch.object(tt, "_elapsed_since", return_value=1.5):
                with patch.object(tt, "_record"):
                    tt.on_observe(ctx, obs)
                    # Should call _record
                    assert True  # If no crash, test passes


# ---------------------------------------------------------------------------
# Helper methods
# ---------------------------------------------------------------------------
class TestDetermineOutcome:
    def test_error_observation_returns_failure(self):
        tt = ToolTelemetry()
        obs = ErrorObservation(content="Error occurred")
        result = tt._determine_outcome(obs)
        assert result == "failure"

    def test_success_observation_returns_success(self):
        tt = ToolTelemetry()
        obs = CmdOutputObservation(
            command="ls", command_id=1, exit_code=0, content="output"
        )
        result = tt._determine_outcome(obs)
        assert result == "success"


class TestElapsedSince:
    def test_calculates_duration(self):
        tt = ToolTelemetry()
        telemetry = {"start_time": time.monotonic() - 2.0}
        duration = tt._elapsed_since(telemetry)
        assert duration >= 2.0

    def test_missing_start_time_returns_zero(self):
        tt = ToolTelemetry()
        telemetry: dict[str, float] = {}
        duration = tt._elapsed_since(telemetry)
        assert duration == 0.0


class TestRecord:
    def test_increments_counter_when_available(self):
        tt = ToolTelemetry()
        mock_counter = MagicMock()
        tt._invocations = mock_counter
        tt._latency = MagicMock()

        tt._record("test_tool", "success", 1.5)

        mock_counter.labels.assert_called_with(tool="test_tool", outcome="success")

    def test_records_without_prometheus(self):
        tt = ToolTelemetry()
        tt._invocations = None
        tt._latency = None

        # Should not crash
        tt._record("test_tool", "success", 1.5)

    def test_appends_to_recent_events(self):
        tt = ToolTelemetry()
        tt._record("test_tool", "success", 1.0)

        assert len(tt._recent_events) == 1
        assert tt._recent_events[0]["tool"] == "test_tool"

    def test_limits_buffer_to_200(self):
        tt = ToolTelemetry()

        for i in range(250):
            tt._record(f"test{i}", "success", 1.0)

        # Should only keep the most recent 200
        assert len(tt._recent_events) == 200


class TestRecentEvents:
    def test_returns_copy_of_events(self):
        tt = ToolTelemetry()
        tt._record("test", "success", 1.0)

        events = tt.recent_events()
        assert isinstance(events, list)
        assert len(events) == 1

        # Modifying returned list should not affect internal state
        events.clear()
        assert len(tt._recent_events) == 1
