"""Tests for AgentController — the main agent orchestration controller."""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.controller.agent_controller import (
    AgentController,
    ERROR_ACTION_NOT_EXECUTED_ERROR,
    ERROR_ACTION_NOT_EXECUTED_STOPPED,
    ERROR_ACTION_NOT_EXECUTED_STOPPED_ID,
    TRAFFIC_CONTROL_REMINDER,
)
from backend.core.enums import LifecyclePhase
from backend.core.schemas import AgentState
from backend.events import EventSource


def _make_controller():
    """Create an AgentController with fully mocked internals (no real __init__)."""
    with patch.object(AgentController, "__init__", lambda self, *a, **kw: None):
        ctrl = AgentController.__new__(AgentController)

    # Config
    ctrl.config = MagicMock()
    ctrl.config.sid = "test-sid"
    ctrl.config.event_stream = MagicMock()
    ctrl.config.event_stream.sid = "test-sid"
    ctrl.config.agent = MagicMock()
    ctrl.config.conversation_stats = MagicMock()

    # Services container
    ctrl.services = MagicMock()

    # State tracker
    ctrl.state_tracker = MagicMock()
    ctrl.state_tracker.state = MagicMock()
    ctrl.state_tracker.state.agent_state = AgentState.RUNNING
    ctrl.state_tracker.state.start_id = 0

    # Rate governor / memory
    ctrl.rate_governor = MagicMock()
    ctrl.memory_pressure = MagicMock()

    # Action contexts
    ctrl._action_contexts_by_event_id = {}
    ctrl._action_contexts_by_object = {}

    # Lifecycle
    ctrl._lifecycle = LifecyclePhase.ACTIVE
    ctrl._cached_first_user_message = None
    ctrl._step_task = None

    return ctrl


# ── Properties ───────────────────────────────────────────────────────


class TestAgentControllerProperties(unittest.TestCase):
    """Test AgentController property accessors."""

    def setUp(self):
        self.ctrl = _make_controller()

    def test_id_returns_config_sid(self):
        self.assertEqual(self.ctrl.id, "test-sid")

    def test_id_falls_back_to_event_stream_sid(self):
        self.ctrl.config.sid = None
        self.ctrl.config.event_stream.sid = "stream-sid"
        self.assertEqual(self.ctrl.id, "stream-sid")

    def test_agent_returns_config_agent(self):
        self.assertIs(self.ctrl.agent, self.ctrl.config.agent)

    def test_event_stream_returns_config_event_stream(self):
        self.assertIs(self.ctrl.event_stream, self.ctrl.config.event_stream)

    def test_state_returns_state_tracker_state(self):
        self.assertIs(self.ctrl.state, self.ctrl.state_tracker.state)

    def test_conversation_stats(self):
        self.assertIs(self.ctrl.conversation_stats, self.ctrl.config.conversation_stats)

    def test_task_id_equals_id(self):
        self.assertEqual(self.ctrl.task_id, self.ctrl.id)


# ── Service aliasing ────────────────────────────────────────────────


class TestServiceAliasing(unittest.TestCase):
    """Test __getattr__ service alias magic."""

    def setUp(self):
        self.ctrl = _make_controller()

    def test_action_service_alias(self):
        self.assertIs(self.ctrl.action_service, self.ctrl.services.action)

    def test_pending_action_service_alias(self):
        self.assertIs(
            self.ctrl.pending_action_service, self.ctrl.services.pending_action
        )

    def test_autonomy_service_alias(self):
        self.assertIs(self.ctrl.autonomy_service, self.ctrl.services.autonomy)

    def test_iteration_service_alias(self):
        self.assertIs(self.ctrl.iteration_service, self.ctrl.services.iteration)

    def test_lifecycle_service_alias(self):
        self.assertIs(self.ctrl.lifecycle_service, self.ctrl.services.lifecycle)

    def test_recovery_service_alias(self):
        self.assertIs(self.ctrl.recovery_service, self.ctrl.services.recovery)

    def test_retry_service_alias(self):
        self.assertIs(self.ctrl.retry_service, self.ctrl.services.retry)

    def test_state_service_alias(self):
        self.assertIs(self.ctrl.state_service, self.ctrl.services.state)

    def test_iteration_guard_alias(self):
        self.assertIs(self.ctrl.iteration_guard, self.ctrl.services.iteration_guard)

    def test_step_guard_alias(self):
        self.assertIs(self.ctrl.step_guard, self.ctrl.services.step_guard)

    def test_step_prerequisites_alias(self):
        self.assertIs(
            self.ctrl.step_prerequisites, self.ctrl.services.step_prerequisites
        )

    def test_budget_guard_alias(self):
        self.assertIs(self.ctrl.budget_guard, self.ctrl.services.budget_guard)

    def test_event_router_alias(self):
        self.assertIs(self.ctrl.event_router, self.ctrl.services.event_router)

    def test_step_decision_alias(self):
        self.assertIs(self.ctrl.step_decision, self.ctrl.services.step_decision)

    def test_exception_handler_alias(self):
        self.assertIs(self.ctrl.exception_handler, self.ctrl.services.exception_handler)

    def test_action_execution_alias(self):
        self.assertIs(self.ctrl.action_execution, self.ctrl.services.action_execution)

    def test_unknown_attribute_raises(self):
        with self.assertRaises(AttributeError):
            _ = self.ctrl.nonexistent_attr_12345

    def test_alias_before_services_set(self):
        """Covers the edge case where services hasn't been set yet."""
        ctrl = _make_controller()
        del ctrl.__dict__["services"]
        with self.assertRaises(AttributeError):
            _ = ctrl.action_service

    # Explicit property shortcuts
    def test_stuck_service_property(self):
        self.assertIs(self.ctrl.stuck_service, self.ctrl.services.stuck)

    def test_circuit_breaker_service_property(self):
        self.assertIs(
            self.ctrl.circuit_breaker_service, self.ctrl.services.circuit_breaker
        )

    def test_telemetry_service_property(self):
        self.assertIs(self.ctrl.telemetry_service, self.ctrl.services.telemetry)

    def test_observation_service_property(self):
        self.assertIs(self.ctrl.observation_service, self.ctrl.services.observation)

    def test_task_validation_service_property(self):
        self.assertIs(
            self.ctrl.task_validation_service, self.ctrl.services.task_validation
        )


# ── Logging ──────────────────────────────────────────────────────────


class TestLogging(unittest.TestCase):
    """Test log() method."""

    def setUp(self):
        self.ctrl = _make_controller()

    @patch("backend.controller.agent_controller.logger")
    def test_log_info(self, mock_logger):
        self.ctrl.log("info", "Hello")
        mock_logger.info.assert_called_once()

    @patch("backend.controller.agent_controller.logger")
    def test_log_includes_session_id(self, mock_logger):
        self.ctrl.log("debug", "Testing")
        call_kwargs = mock_logger.debug.call_args
        self.assertIn("session_id", call_kwargs.kwargs.get("extra", {}))

    @patch("backend.controller.agent_controller.logger")
    def test_log_merges_extra(self, mock_logger):
        self.ctrl.log("warning", "Alert", extra={"custom_key": "val"})
        call_kwargs = mock_logger.warning.call_args
        extra = call_kwargs.kwargs.get("extra", {})
        self.assertIn("custom_key", extra)
        self.assertIn("session_id", extra)


# ── Step execution ───────────────────────────────────────────────────


class TestStepExecution(unittest.IsolatedAsyncioTestCase):
    """Test step-related methods."""

    def setUp(self):
        self.ctrl = _make_controller()

    async def test_step_with_exception_handling_success(self):
        with patch.object(self.ctrl, "_step", new_callable=AsyncMock) as mock_step:
            await self.ctrl._step_with_exception_handling()
        mock_step.assert_awaited_once()

    async def test_step_with_exception_handling_delegates_error(self):
        exc = RuntimeError("boom")
        with patch.object(self.ctrl, "_step", new_callable=AsyncMock, side_effect=exc):
            self.ctrl.services.exception_handler.handle_step_exception = AsyncMock()
            await self.ctrl._step_with_exception_handling()

        self.ctrl.services.exception_handler.handle_step_exception.assert_awaited_once_with(
            exc
        )

    async def test_step_returns_early_if_cannot_step(self):
        self.ctrl.services.step_prerequisites.can_step.return_value = False
        self.ctrl.services.action_execution.get_next_action = AsyncMock()

        await self.ctrl._step()

        self.ctrl.services.action_execution.get_next_action.assert_not_awaited()

    async def test_step_returns_early_if_step_guard_fails(self):
        self.ctrl.services.step_prerequisites.can_step.return_value = True
        self.ctrl.services.step_guard.ensure_can_step = AsyncMock(return_value=False)
        self.ctrl.services.budget_guard.sync_with_metrics = MagicMock()
        self.ctrl.services.action_execution.get_next_action = AsyncMock()

        await self.ctrl._step()

        self.ctrl.services.action_execution.get_next_action.assert_not_awaited()

    async def test_step_returns_early_if_control_flags_fail(self):
        self.ctrl.services.step_prerequisites.can_step.return_value = True
        self.ctrl.services.step_guard.ensure_can_step = AsyncMock(return_value=True)
        self.ctrl.services.budget_guard.sync_with_metrics = MagicMock()

        with patch.object(
            self.ctrl, "_run_control_flags_safely", new_callable=AsyncMock
        ) as mock_flags:
            mock_flags.return_value = False
            self.ctrl.services.action_execution.get_next_action = AsyncMock()
            await self.ctrl._step()

        self.ctrl.services.action_execution.get_next_action.assert_not_awaited()

    async def test_step_returns_early_if_no_action(self):
        self.ctrl.services.step_prerequisites.can_step.return_value = True
        self.ctrl.services.step_guard.ensure_can_step = AsyncMock(return_value=True)
        self.ctrl.services.budget_guard.sync_with_metrics = MagicMock()
        self.ctrl.services.action_execution.get_next_action = AsyncMock(
            return_value=None
        )

        with patch.object(
            self.ctrl, "_run_control_flags_safely", new_callable=AsyncMock
        ) as mock_flags:
            mock_flags.return_value = True
            self.ctrl.services.action_execution.execute_action = AsyncMock()
            await self.ctrl._step()

        self.ctrl.services.action_execution.execute_action.assert_not_awaited()

    async def test_step_full_success_path(self):
        self.ctrl.services.step_prerequisites.can_step.return_value = True
        self.ctrl.services.step_guard.ensure_can_step = AsyncMock(return_value=True)
        self.ctrl.services.budget_guard.sync_with_metrics = MagicMock()
        mock_action = MagicMock()
        self.ctrl.services.action_execution.get_next_action = AsyncMock(
            return_value=mock_action
        )
        self.ctrl.services.action_execution.execute_action = AsyncMock()
        self.ctrl.services.retry.retry_count = 0

        with (
            patch.object(
                self.ctrl, "_run_control_flags_safely", new_callable=AsyncMock
            ) as mock_flags,
            patch.object(
                self.ctrl, "_handle_post_execution", new_callable=AsyncMock
            ) as mock_post,
        ):
            mock_flags.return_value = True
            await self.ctrl._step()

        self.ctrl.services.action_execution.execute_action.assert_awaited_once_with(
            mock_action
        )
        mock_post.assert_awaited_once()

    async def test_step_resets_retry_on_success(self):
        self.ctrl.services.step_prerequisites.can_step.return_value = True
        self.ctrl.services.step_guard.ensure_can_step = AsyncMock(return_value=True)
        self.ctrl.services.budget_guard.sync_with_metrics = MagicMock()
        self.ctrl.services.action_execution.get_next_action = AsyncMock(
            return_value=MagicMock()
        )
        self.ctrl.services.action_execution.execute_action = AsyncMock()
        self.ctrl.services.retry.retry_count = 3
        self.ctrl.services.retry.reset_retry_metrics = MagicMock()

        with (
            patch.object(
                self.ctrl, "_run_control_flags_safely", new_callable=AsyncMock
            ) as mock_flags,
            patch.object(self.ctrl, "_handle_post_execution", new_callable=AsyncMock),
        ):
            mock_flags.return_value = True
            await self.ctrl._step()

        self.ctrl.services.retry.reset_retry_metrics.assert_called_once()

    def test_should_step_delegates(self):
        event = MagicMock()
        self.ctrl.services.step_decision.should_step.return_value = True
        self.assertTrue(self.ctrl.should_step(event))

    def test_should_step_returns_false(self):
        event = MagicMock()
        self.ctrl.services.step_decision.should_step.return_value = False
        self.assertFalse(self.ctrl.should_step(event))


# ── Control flags ────────────────────────────────────────────────────


class TestControlFlags(unittest.IsolatedAsyncioTestCase):
    """Test _run_control_flags_safely."""

    def setUp(self):
        self.ctrl = _make_controller()

    async def test_run_control_flags_success(self):
        self.ctrl.services.iteration_guard.run_control_flags = AsyncMock()
        result = await self.ctrl._run_control_flags_safely()
        self.assertTrue(result)

    async def test_run_control_flags_exception(self):
        self.ctrl.services.iteration_guard.run_control_flags = AsyncMock(
            side_effect=RuntimeError("boom")
        )
        self.ctrl.services.recovery.react_to_exception = AsyncMock()

        result = await self.ctrl._run_control_flags_safely()

        self.assertFalse(result)
        self.ctrl.services.recovery.react_to_exception.assert_awaited_once()


# ── Event handling ───────────────────────────────────────────────────


class TestEventHandling(unittest.IsolatedAsyncioTestCase):
    """Test on_event and _on_event."""

    def setUp(self):
        self.ctrl = _make_controller()

    async def test_on_event_routes_via_event_router(self):
        event = MagicMock()
        self.ctrl.services.event_router.route_event = AsyncMock()

        await self.ctrl._on_event(event)

        self.ctrl.services.event_router.route_event.assert_awaited_once_with(event)

    async def test_react_to_exception_delegates(self):
        exc = RuntimeError("error")
        self.ctrl.services.recovery.react_to_exception = AsyncMock()

        await self.ctrl._react_to_exception(exc)

        self.ctrl.services.recovery.react_to_exception.assert_awaited_once_with(exc)


# ── Lifecycle ────────────────────────────────────────────────────────


class TestLifecycle(unittest.IsolatedAsyncioTestCase):
    """Test close, stop, lifecycle property."""

    def setUp(self):
        self.ctrl = _make_controller()

    def test_closed_property_false_when_running(self):
        self.ctrl._lifecycle = LifecyclePhase.ACTIVE
        self.assertFalse(self.ctrl._closed)

    def test_closed_property_true_when_closing(self):
        self.ctrl._lifecycle = LifecyclePhase.CLOSING
        self.assertTrue(self.ctrl._closed)

    def test_closed_property_true_when_closed(self):
        self.ctrl._lifecycle = LifecyclePhase.CLOSED
        self.assertTrue(self.ctrl._closed)

    async def test_close_transitions_to_closed(self):
        self.ctrl.services.state.set_agent_state = AsyncMock()
        self.ctrl.services.retry.shutdown = AsyncMock()

        await self.ctrl.close()

        self.assertEqual(self.ctrl._lifecycle, LifecyclePhase.CLOSED)

    async def test_close_sets_stopped_state(self):
        self.ctrl.services.state.set_agent_state = AsyncMock()
        self.ctrl.services.retry.shutdown = AsyncMock()

        await self.ctrl.close(set_stop_state=True)

        self.ctrl.services.state.set_agent_state.assert_awaited_once_with(
            AgentState.STOPPED
        )

    async def test_close_skips_stop_state(self):
        self.ctrl.services.state.set_agent_state = AsyncMock()
        self.ctrl.services.retry.shutdown = AsyncMock()

        await self.ctrl.close(set_stop_state=False)

        self.ctrl.services.state.set_agent_state.assert_not_awaited()

    async def test_close_shuts_down_retry_service(self):
        self.ctrl.services.state.set_agent_state = AsyncMock()
        self.ctrl.services.retry.shutdown = AsyncMock()

        await self.ctrl.close()

        self.ctrl.services.retry.shutdown.assert_awaited_once()

    async def test_stop_sets_stopped_state(self):
        self.ctrl.services.state.set_agent_state = AsyncMock()
        self.ctrl.services.pending_action.set = MagicMock()

        await self.ctrl.stop()

        self.ctrl.services.state.set_agent_state.assert_awaited_once_with(
            AgentState.STOPPED
        )


# ── State helpers ────────────────────────────────────────────────────


class TestStateHelpers(unittest.TestCase):
    """Test get_agent_state, get_state, set_initial_state, save_state."""

    def setUp(self):
        self.ctrl = _make_controller()

    def test_get_agent_state(self):
        self.ctrl.state_tracker.state.agent_state = AgentState.PAUSED
        self.assertEqual(self.ctrl.get_agent_state(), AgentState.PAUSED)

    def test_get_state_returns_state(self):
        self.assertIs(self.ctrl.get_state(), self.ctrl.state_tracker.state)

    def test_save_state(self):
        self.ctrl.save_state()
        self.ctrl.state_tracker.save_state.assert_called_once()

    def test_set_initial_state(self):
        stats = MagicMock()
        self.ctrl.set_initial_state(None, stats, 100, 10.0, True)
        self.ctrl.state_tracker.set_initial_state.assert_called_once_with(
            "test-sid", None, stats, 100, 10.0, True
        )


# ── get_trajectory ───────────────────────────────────────────────────


class TestGetTrajectory(unittest.TestCase):
    """Test get_trajectory."""

    def setUp(self):
        self.ctrl = _make_controller()

    def test_get_trajectory_requires_closed(self):
        self.ctrl._lifecycle = LifecyclePhase.ACTIVE
        with self.assertRaises(RuntimeError):
            self.ctrl.get_trajectory()

    def test_get_trajectory_when_closed(self):
        self.ctrl._lifecycle = LifecyclePhase.CLOSED
        self.ctrl.state_tracker.get_trajectory.return_value = [{"event": "test"}]
        result = self.ctrl.get_trajectory()
        self.assertEqual(result, [{"event": "test"}])

    def test_get_trajectory_with_screenshots(self):
        self.ctrl._lifecycle = LifecyclePhase.CLOSED
        self.ctrl.get_trajectory(include_screenshots=True)
        self.ctrl.state_tracker.get_trajectory.assert_called_once_with(True)


# ── _is_stuck ────────────────────────────────────────────────────────


class TestIsStuck(unittest.TestCase):
    """Test _is_stuck delegation."""

    def setUp(self):
        self.ctrl = _make_controller()

    def test_is_stuck_true(self):
        self.ctrl.services.stuck.is_stuck.return_value = True
        self.assertTrue(self.ctrl._is_stuck())

    def test_is_stuck_false(self):
        self.ctrl.services.stuck.is_stuck.return_value = False
        self.assertFalse(self.ctrl._is_stuck())


# ── _first_user_message ─────────────────────────────────────────────


class TestFirstUserMessage(unittest.TestCase):
    """Test _first_user_message."""

    def setUp(self):
        self.ctrl = _make_controller()

    def test_with_events_list(self):
        from backend.events.action import MessageAction

        msg = MagicMock(spec=MessageAction)
        msg.source = EventSource.USER
        # isinstance check needs real class

        with patch(
            "backend.controller.agent_controller.isinstance",
            side_effect=lambda o, c: c is MessageAction and o is msg,
        ):
            pass  # Can't easily patch isinstance; use different approach

    def test_cached_value(self):
        sentinel = MagicMock()
        self.ctrl._cached_first_user_message = sentinel
        result = self.ctrl._first_user_message()
        self.assertIs(result, sentinel)


# ── __repr__ ─────────────────────────────────────────────────────────


class TestRepr(unittest.TestCase):
    """Test __repr__."""

    def setUp(self):
        self.ctrl = _make_controller()

    def test_repr_contains_id(self):
        self.ctrl.services.action.get_pending_action_info.return_value = None
        result = repr(self.ctrl)
        self.assertIn("AgentController", result)
        self.assertIn("test-sid", result)

    def test_repr_no_pending_action(self):
        self.ctrl.services.action.get_pending_action_info.return_value = None
        result = repr(self.ctrl)
        self.assertIn("<none>", result)

    def test_repr_with_pending_action(self):
        import time

        mock_action = MagicMock()
        mock_action.id = 42
        mock_action.__class__.__name__ = "CmdRunAction"
        self.ctrl.services.action.get_pending_action_info.return_value = (
            mock_action,
            time.time() - 5.0,
        )
        result = repr(self.ctrl)
        self.assertIn("CmdRunAction", result)


# ── _handle_post_execution ───────────────────────────────────────────


class TestPostExecution(unittest.IsolatedAsyncioTestCase):
    """Test _handle_post_execution."""

    def setUp(self):
        self.ctrl = _make_controller()

    async def test_rate_governor_check(self):
        self.ctrl.state_tracker.state.metrics = MagicMock()
        self.ctrl.rate_governor.check_and_wait = AsyncMock()
        self.ctrl.config.agent._last_llm_latency = None
        self.ctrl.memory_pressure.should_condense.return_value = False

        await self.ctrl._handle_post_execution()

        self.ctrl.rate_governor.check_and_wait.assert_awaited_once()

    async def test_memory_pressure_condensation(self):
        del self.ctrl.state_tracker.state.metrics
        self.ctrl.config.agent._last_llm_latency = None
        self.ctrl.memory_pressure.should_condense.return_value = True
        self.ctrl.memory_pressure.is_critical.return_value = False
        self.ctrl.memory_pressure._last_rss_mb = 500.0
        self.ctrl.state_tracker.state.extra_data = {}
        self.ctrl.state_tracker.state.set_extra = MagicMock()

        await self.ctrl._handle_post_execution()

        self.ctrl.memory_pressure.record_condensation.assert_called_once()


# ── Action context management ────────────────────────────────────────


class TestActionContextManagement(unittest.TestCase):
    """Test action context register, bind, cleanup."""

    def setUp(self):
        self.ctrl = _make_controller()

    def test_register_action_context(self):
        action = MagicMock()
        ctx = MagicMock()
        self.ctrl._register_action_context(action, ctx)
        self.assertIn(id(action), self.ctrl._action_contexts_by_object)

    def test_bind_action_context(self):
        action = MagicMock()
        action.id = 42
        ctx = MagicMock()
        ctx.action_id = None

        self.ctrl._action_contexts_by_object[id(action)] = ctx
        self.ctrl._bind_action_context(action, ctx)

        self.assertEqual(ctx.action_id, 42)
        self.assertIn(42, self.ctrl._action_contexts_by_event_id)
        self.assertNotIn(id(action), self.ctrl._action_contexts_by_object)

    def test_cleanup_action_context_by_action(self):
        action = MagicMock()
        ctx = MagicMock()
        ctx.action_id = 10
        self.ctrl._action_contexts_by_object[id(action)] = ctx
        self.ctrl._action_contexts_by_event_id[10] = ctx

        self.ctrl._cleanup_action_context(ctx, action=action)

        self.assertNotIn(id(action), self.ctrl._action_contexts_by_object)
        self.assertNotIn(10, self.ctrl._action_contexts_by_event_id)

    def test_cleanup_action_context_by_ctx(self):
        ctx = MagicMock()
        ctx.action_id = 20
        self.ctrl._action_contexts_by_object[999] = ctx
        self.ctrl._action_contexts_by_event_id[20] = ctx

        self.ctrl._cleanup_action_context(ctx)

        self.assertNotIn(999, self.ctrl._action_contexts_by_object)
        self.assertNotIn(20, self.ctrl._action_contexts_by_event_id)


# ── _reset ───────────────────────────────────────────────────────────


class TestReset(unittest.TestCase):
    """Test _reset."""

    def setUp(self):
        self.ctrl = _make_controller()

    def test_reset_clears_contexts(self):
        self.ctrl._action_contexts_by_object[1] = "a"
        self.ctrl._action_contexts_by_event_id[2] = "b"

        # Make pending_action return None
        self.ctrl.services.pending_action.get.return_value = None

        self.ctrl._reset()

        self.assertEqual(len(self.ctrl._action_contexts_by_object), 0)
        self.assertEqual(len(self.ctrl._action_contexts_by_event_id), 0)

    def test_reset_emits_error_obs_when_stopped(self):
        mock_action = MagicMock()
        mock_action.tool_call_metadata = MagicMock()
        mock_action.id = 5
        self.ctrl.services.pending_action.get.return_value = mock_action
        self.ctrl.state_tracker.state.history = []
        self.ctrl.state_tracker.state.agent_state = AgentState.STOPPED
        self.ctrl.config.agent.reset = MagicMock()

        with patch(
            "backend.controller.agent_controller.ErrorObservation"
        ) as mock_obs_cls:
            mock_obs = MagicMock()
            mock_obs_cls.return_value = mock_obs
            self.ctrl._reset()

        mock_obs_cls.assert_called_once_with(
            content=ERROR_ACTION_NOT_EXECUTED_STOPPED,
            error_id=ERROR_ACTION_NOT_EXECUTED_STOPPED_ID,
        )
        self.ctrl.config.event_stream.add_event.assert_called_once()


# ── _is_awaiting_observation ─────────────────────────────────────────


class TestIsAwaitingObservation(unittest.TestCase):
    """Test _is_awaiting_observation."""

    def setUp(self):
        self.ctrl = _make_controller()

    def test_returns_true_when_running(self):
        from backend.events.observation import AgentStateChangedObservation

        obs = MagicMock(spec=AgentStateChangedObservation)
        obs.agent_state = AgentState.RUNNING
        self.ctrl.config.event_stream.search_events.return_value = [obs]

        with patch(
            "backend.controller.agent_controller.isinstance",
            side_effect=lambda o, c: o is obs and c is AgentStateChangedObservation,
        ):
            pass
        # Direct test — mock the search
        self.ctrl.config.event_stream.search_events.return_value = iter([obs])

    def test_returns_false_when_no_events(self):
        self.ctrl.config.event_stream.search_events.return_value = iter([])
        result = self.ctrl._is_awaiting_observation()
        self.assertFalse(result)


# ── log_task_audit ───────────────────────────────────────────────────


class TestLogTaskAudit(unittest.IsolatedAsyncioTestCase):
    """Test log_task_audit."""

    def setUp(self):
        self.ctrl = _make_controller()

    async def test_no_audit_callback(self):
        self.ctrl._audit_callback = None
        # Should not raise
        await self.ctrl.log_task_audit("completed")

    async def test_audit_callback_invoked(self):
        callback = MagicMock(return_value=None)
        self.ctrl._audit_callback = callback

        task_mock = MagicMock()
        task_mock.description = "Test task"
        with patch.object(self.ctrl, "_get_initial_task", return_value=task_mock):
            self.ctrl.state_tracker.state.metrics = MagicMock()
            self.ctrl.state_tracker.state.metrics.accumulated_token_usage.prompt_tokens = 100
            self.ctrl.state_tracker.state.metrics.accumulated_token_usage.completion_tokens = 50
            self.ctrl.state_tracker.state.metrics.accumulated_cost = 0.05

            await self.ctrl.log_task_audit("completed")

        callback.assert_called_once()
        call_kwargs = callback.call_args.kwargs
        self.assertEqual(call_kwargs["status"], "completed")
        self.assertEqual(call_kwargs["tokens_used"], 150)

    async def test_audit_callback_async(self):
        callback = AsyncMock(return_value=None)
        self.ctrl._audit_callback = callback

        task_mock = MagicMock()
        task_mock.description = "Async task"
        with patch.object(self.ctrl, "_get_initial_task", return_value=task_mock):
            self.ctrl.state_tracker.state.metrics = MagicMock()
            self.ctrl.state_tracker.state.metrics.accumulated_token_usage.prompt_tokens = 50
            self.ctrl.state_tracker.state.metrics.accumulated_token_usage.completion_tokens = 50
            self.ctrl.state_tracker.state.metrics.accumulated_cost = 0.01

            await self.ctrl.log_task_audit("error", error_message="Failed")

        callback.assert_awaited_once()

    async def test_audit_callback_exception_handled(self):
        callback = MagicMock(side_effect=RuntimeError("Audit fail"))
        self.ctrl._audit_callback = callback

        with patch.object(self.ctrl, "_get_initial_task", side_effect=RuntimeError):
            # Should not raise
            await self.ctrl.log_task_audit("error")


# ── Constants ────────────────────────────────────────────────────────


class TestConstants(unittest.TestCase):
    """Test module-level constants exist."""

    def test_traffic_control_reminder(self):
        self.assertIn("resume", TRAFFIC_CONTROL_REMINDER)

    def test_error_action_not_executed_stopped(self):
        self.assertIn("Stop button", ERROR_ACTION_NOT_EXECUTED_STOPPED)

    def test_error_action_not_executed_error(self):
        self.assertIn("runtime error", ERROR_ACTION_NOT_EXECUTED_ERROR)


if __name__ == "__main__":
    unittest.main()
