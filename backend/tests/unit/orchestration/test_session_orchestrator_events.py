# pyright: reportAttributeAccessIssue=false, reportMissingParameterType=false, reportPrivateUsage=false, reportUnknownArgumentType=false, reportUnknownLambdaType=false, reportUnknownMemberType=false, reportUnknownParameterType=false, reportUnknownVariableType=false
# mypy: disable-error-code="assignment,attr-defined,method-assign,misc"
"""Tests for SessionOrchestrator — the main agent orchestration controller."""
# pylint: disable=protected-access,too-many-lines

import asyncio
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from backend.core.enums import LifecyclePhase
from backend.core.schemas import AgentState
from backend.ledger import EventSource
from backend.ledger.action import MessageAction
from backend.orchestration.action_scheduler import ActionScheduler
from backend.orchestration.orchestration_config import OrchestrationConfig
from backend.orchestration.session_orchestrator import (
    ERROR_ACTION_NOT_EXECUTED_ERROR,
    ERROR_ACTION_NOT_EXECUTED_STOPPED,
    ERROR_ACTION_NOT_EXECUTED_STOPPED_ID,
    TRAFFIC_CONTROL_REMINDER,
    SessionOrchestrator,
)


class TestEventHandling:
    """Test on_event and _on_event."""

    @pytest.fixture(autouse=True)
    def _setup(self, ctrl):
        self.ctrl = ctrl


    @pytest.mark.asyncio
    async def test_on_event_routes_via_event_router(self):
        event = MagicMock()
        self.ctrl.services.event_router.route_event = AsyncMock()

        await self.ctrl._on_event(event)

        self.ctrl.services.event_router.route_event.assert_awaited_once_with(event)

    @pytest.mark.asyncio
    async def test_react_to_exception_delegates(self):
        exc = RuntimeError('error')
        self.ctrl.services.recovery.react_to_exception = AsyncMock()

        await self.ctrl._react_to_exception(exc)

        self.ctrl.services.recovery.react_to_exception.assert_awaited_once_with(exc)


# ── Lifecycle ────────────────────────────────────────────────────────




class TestLifecycle:
    """Test close, stop, lifecycle property."""

    @pytest.fixture(autouse=True)
    def _setup(self, ctrl):
        self.ctrl = ctrl


    def test_closed_property_false_when_running(self):
        self.ctrl._lifecycle = LifecyclePhase.ACTIVE
        assert not self.ctrl._closed

    def test_closed_property_true_when_closing(self):
        self.ctrl._lifecycle = LifecyclePhase.CLOSING
        assert self.ctrl._closed

    def test_closed_property_true_when_closed(self):
        self.ctrl._lifecycle = LifecyclePhase.CLOSED
        assert self.ctrl._closed

    @pytest.mark.asyncio
    async def test_close_transitions_to_closed(self):
        self.ctrl.services.state.set_agent_state = AsyncMock()
        self.ctrl.services.retry.shutdown = AsyncMock()

        await self.ctrl.close()

        assert self.ctrl._lifecycle == LifecyclePhase.CLOSED

    @pytest.mark.asyncio
    async def test_close_sets_stopped_state(self):
        self.ctrl.services.state.set_agent_state = AsyncMock()
        self.ctrl.services.retry.shutdown = AsyncMock()

        await self.ctrl.close(set_stop_state=True)

        self.ctrl.services.state.set_agent_state.assert_awaited_once_with(
            AgentState.STOPPED
        )

    @pytest.mark.asyncio
    async def test_close_skips_stop_state(self):
        self.ctrl.services.state.set_agent_state = AsyncMock()
        self.ctrl.services.retry.shutdown = AsyncMock()

        await self.ctrl.close(set_stop_state=False)

        self.ctrl.services.state.set_agent_state.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_close_shuts_down_retry_service(self):
        self.ctrl.services.state.set_agent_state = AsyncMock()
        self.ctrl.services.retry.shutdown = AsyncMock()

        await self.ctrl.close()

        self.ctrl.services.retry.shutdown.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_shuts_down_pending_action_service(self):
        self.ctrl.services.state.set_agent_state = AsyncMock()
        self.ctrl.services.retry.shutdown = AsyncMock()
        self.ctrl.services.pending_action.shutdown = MagicMock()

        await self.ctrl.close()

        self.ctrl.services.pending_action.shutdown.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_close_closes_event_stream(self):
        self.ctrl.services.state.set_agent_state = AsyncMock()
        self.ctrl.services.retry.shutdown = AsyncMock()

        await self.ctrl.close()

        self.ctrl.event_stream.close.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_stop_sets_stopped_state(self):
        self.ctrl.services.state.set_agent_state = AsyncMock()
        self.ctrl.services.pending_action.set = MagicMock()

        await self.ctrl.stop()

        self.ctrl.services.state.set_agent_state.assert_awaited_once_with(
            AgentState.STOPPED
        )

    @pytest.mark.asyncio
    async def test_stop_cancels_active_step_task_and_executor(self):
        self.ctrl.services.state.set_agent_state = AsyncMock()
        self.ctrl.services.pending_action.set = MagicMock()
        executor = MagicMock()
        self.ctrl.config.agent.executor = executor
        task_started = asyncio.Event()

        async def slow_step() -> None:
            task_started.set()
            await asyncio.sleep(60)

        self.ctrl._step_task = asyncio.create_task(slow_step())
        await asyncio.wait_for(task_started.wait(), timeout=1)

        await self.ctrl.stop()

        executor.cancel_step.assert_called_once_with()
        assert self.ctrl._step_task.cancelled()
        self.ctrl.services.state.set_agent_state.assert_awaited_once_with(
            AgentState.STOPPED
        )

    @pytest.mark.asyncio
    async def test_stop_hard_kills_async_runtime_when_available(self):
        self.ctrl.services.state.set_agent_state = AsyncMock()
        self.ctrl.services.pending_action.set = MagicMock()
        runtime = MagicMock()
        runtime.hard_kill = AsyncMock()
        self.ctrl.runtime = runtime

        await self.ctrl.stop()

        runtime.hard_kill.assert_awaited_once_with()
        self.ctrl.services.state.set_agent_state.assert_awaited_once_with(
            AgentState.STOPPED
        )

    @pytest.mark.asyncio
    async def test_stop_hard_kills_sync_runtime_when_available(self):
        self.ctrl.services.state.set_agent_state = AsyncMock()
        self.ctrl.services.pending_action.set = MagicMock()
        runtime = MagicMock()
        runtime.hard_kill = MagicMock()
        self.ctrl.runtime = runtime

        await self.ctrl.stop()

        runtime.hard_kill.assert_called_once_with()
        self.ctrl.services.state.set_agent_state.assert_awaited_once_with(
            AgentState.STOPPED
        )


# ── State helpers ────────────────────────────────────────────────────




class TestPostExecution:
    """Test _handle_post_execution."""

    @pytest.fixture(autouse=True)
    def _setup(self, ctrl):
        self.ctrl = ctrl


    @pytest.mark.asyncio
    async def test_rate_governor_check(self):
        self.ctrl.state_tracker.state.metrics = MagicMock()
        self.ctrl.state_tracker.state.metrics.accumulated_token_usage = MagicMock()
        self.ctrl.rate_governor.check_and_wait = AsyncMock()
        self.ctrl.config.agent._last_llm_latency = None
        self.ctrl.memory_pressure.should_condense.return_value = False

        await self.ctrl._handle_post_execution()

        self.ctrl.rate_governor.check_and_wait.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_memory_pressure_condensation(self):
        # No metrics to avoid rate governor path; trigger condensation path
        if hasattr(self.ctrl.state_tracker.state, 'metrics'):
            del self.ctrl.state_tracker.state.metrics
        self.ctrl.config.agent._last_llm_latency = None
        self.ctrl.memory_pressure.should_signal_pressure.return_value = True
        self.ctrl.memory_pressure.is_critical.return_value = False
        self.ctrl.memory_pressure._last_rss_mb = 500.0
        self.ctrl.state_tracker.state.turn_signals = MagicMock()
        self.ctrl.state_tracker.state.set_memory_pressure = MagicMock()

        await self.ctrl._handle_post_execution()

        self.ctrl.memory_pressure.record_condensation.assert_not_called()
        self.ctrl.state_tracker.state.set_memory_pressure.assert_called_once_with(
            'WARNING', source='SessionOrchestrator'
        )

    @pytest.mark.asyncio
    async def test_warning_prewarm_uses_background_compaction_hook(self):
        if hasattr(self.ctrl.state_tracker.state, 'metrics'):
            del self.ctrl.state_tracker.state.metrics
        self.ctrl.config.agent._last_llm_latency = None
        self.ctrl.memory_pressure.should_signal_pressure.return_value = True
        self.ctrl.memory_pressure.is_critical.return_value = False
        self.ctrl.memory_pressure.is_prewarming = False
        self.ctrl.memory_pressure.has_prewarmed = False
        self.ctrl.memory_pressure._last_rss_mb = 500.0
        self.ctrl.state_tracker.state.history = [MessageAction(content='start')]
        self.ctrl.state_tracker.state.turn_signals = MagicMock()
        self.ctrl.state_tracker.state.set_memory_pressure = MagicMock()

        compactor = SimpleNamespace(
            compacted_history_background=AsyncMock(return_value='background'),
            compacted_history=AsyncMock(return_value='foreground'),
        )
        self.ctrl.config.agent.memory_manager = SimpleNamespace(compactor=compactor)

        await self.ctrl._handle_post_execution()

        coro_factory = self.ctrl.memory_pressure.start_prewarm.call_args.args[0]
        result = await coro_factory()

        assert result == 'background'
        compactor.compacted_history_background.assert_awaited_once()
        compactor.compacted_history.assert_not_awaited()


# ── Action context management ────────────────────────────────────────


