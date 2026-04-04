"""Tests for backend.orchestration.services.event_router_service."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.schemas import AgentState
from backend.ledger import EventSource
from backend.ledger.action import (
    AgentRejectAction,
    ChangeAgentStateAction,
    MessageAction,
    PlaybookFinishAction,
)
from backend.ledger.observation import Observation
from backend.orchestration.services.event_router_service import EventRouterService


def _make_controller():
    """Create a mock SessionOrchestrator."""
    ctrl = MagicMock()
    ctrl.state_tracker = MagicMock()
    ctrl.set_agent_state_to = AsyncMock()
    ctrl.get_agent_state = MagicMock(return_value=AgentState.LOADING)
    ctrl.observation_service = MagicMock()
    ctrl.observation_service.handle_observation = AsyncMock()
    ctrl.task_validation_service = MagicMock()
    ctrl.task_validation_service.handle_finish = AsyncMock(return_value=True)
    ctrl.log = MagicMock()
    ctrl.log_task_audit = AsyncMock()
    ctrl.state = MagicMock()
    ctrl.event_stream = MagicMock()
    ctrl._pending_action = None
    ctrl._first_user_message = MagicMock(return_value=None)
    return ctrl


class TestEventRouterInit:
    def test_stores_controller(self):
        ctrl = _make_controller()
        svc = EventRouterService(ctrl)
        assert svc._ctrl is ctrl


class TestRouteEvent:
    @pytest.mark.asyncio
    async def test_hidden_event_dropped(self):
        ctrl = _make_controller()
        svc = EventRouterService(ctrl)
        event = MagicMock()
        event.hidden = True
        await svc.route_event(event)
        ctrl.state_tracker.add_history.assert_not_called()

    @pytest.mark.asyncio
    async def test_adds_to_history(self):
        ctrl = _make_controller()
        svc = EventRouterService(ctrl)
        event = MagicMock(spec=[])  # No hidden attr
        # Make it look like neither Action nor Observation
        await svc.route_event(event)
        ctrl.state_tracker.add_history.assert_called_once_with(event)

    @pytest.mark.asyncio
    async def test_plugin_exception_swallowed(self):
        ctrl = _make_controller()
        svc = EventRouterService(ctrl)
        event = MagicMock(spec=[])

        with patch('backend.core.plugin.get_plugin_registry') as mock_reg:
            mock_reg.return_value.dispatch_event = AsyncMock(
                side_effect=RuntimeError('boom')
            )
            # Should not raise
            await svc.route_event(event)
        ctrl.state_tracker.add_history.assert_called_once()


class TestHandleAction:
    @pytest.mark.asyncio
    async def test_change_state_action(self):
        ctrl = _make_controller()
        svc = EventRouterService(ctrl)
        action = ChangeAgentStateAction(agent_state='running')
        await svc._handle_action(action)
        ctrl.set_agent_state_to.assert_called_once_with(AgentState.RUNNING)

    @pytest.mark.asyncio
    async def test_change_state_invalid(self):
        ctrl = _make_controller()
        svc = EventRouterService(ctrl)
        action = ChangeAgentStateAction(agent_state='totally_invalid_state')
        # Should log warning, not raise
        await svc._handle_action(action)
        ctrl.log.assert_called()
        ctrl.set_agent_state_to.assert_not_called()

    @pytest.mark.asyncio
    async def test_message_action_from_user(self):
        ctrl = _make_controller()
        svc = EventRouterService(ctrl)
        action = MessageAction(content='hello')
        action.source = EventSource.USER
        action.id = 1
        action.wait_for_response = False
        await svc._handle_action(action)
        # Should have set state to RUNNING and added a RecallAction
        ctrl.event_stream.add_event.assert_called()
        ctrl.set_agent_state_to.assert_called_with(AgentState.RUNNING)

    @pytest.mark.asyncio
    async def test_message_action_from_agent_wait(self):
        ctrl = _make_controller()
        svc = EventRouterService(ctrl)
        action = MessageAction(content='need input')
        action.source = EventSource.AGENT
        action.wait_for_response = True
        await svc._handle_action(action)
        ctrl.set_agent_state_to.assert_called_with(AgentState.AWAITING_USER_INPUT)

    @pytest.mark.asyncio
    async def test_message_action_from_agent_no_wait(self):
        ctrl = _make_controller()
        svc = EventRouterService(ctrl)
        action = MessageAction(content='info')
        action.source = EventSource.AGENT
        action.wait_for_response = False
        await svc._handle_action(action)
        ctrl.set_agent_state_to.assert_not_called()


class TestHandleFinishAction:
    @pytest.mark.asyncio
    async def test_successful_finish(self):
        ctrl = _make_controller()
        svc = EventRouterService(ctrl)
        action = PlaybookFinishAction(outputs={'result': 'done'})
        await svc._handle_finish_action(action)
        ctrl.state.set_outputs.assert_called_once()
        ctrl.set_agent_state_to.assert_called_with(AgentState.FINISHED)
        ctrl.log_task_audit.assert_called_once_with(status='success')

    @pytest.mark.asyncio
    async def test_validation_failure_aborts(self):
        ctrl = _make_controller()
        ctrl.task_validation_service.handle_finish = AsyncMock(return_value=False)
        svc = EventRouterService(ctrl)
        action = PlaybookFinishAction(outputs={})
        await svc._handle_finish_action(action)
        ctrl.state.set_outputs.assert_not_called()
        ctrl.set_agent_state_to.assert_not_called()


class TestHandleRejectAction:
    @pytest.mark.asyncio
    async def test_reject(self):
        ctrl = _make_controller()
        svc = EventRouterService(ctrl)
        action = AgentRejectAction(outputs={'reason': 'too hard'})
        await svc._handle_reject_action(action)
        ctrl.state.set_outputs.assert_called_once()
        ctrl.set_agent_state_to.assert_called_with(AgentState.REJECTED)


class TestHandleObservation:
    @pytest.mark.asyncio
    async def test_delegates_to_observation_service(self):
        ctrl = _make_controller()
        svc = EventRouterService(ctrl)
        obs = MagicMock(spec=Observation)
        await svc._handle_observation(obs)
        ctrl.observation_service.handle_observation.assert_called_once_with(obs)
