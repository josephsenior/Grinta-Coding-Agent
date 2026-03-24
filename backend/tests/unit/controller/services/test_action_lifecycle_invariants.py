"""Integration-adjacent lifecycle invariants across controller services."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.controller.services.action_service import ActionService
from backend.controller.services.observation_service import ObservationService
from backend.controller.services.pending_action_service import PendingActionService
from backend.core.schemas import AgentState
from backend.events import EventSource
from backend.events.action import CmdRunAction
from backend.events.observation.commands import CmdOutputObservation


class TestActionLifecycleInvariant(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.controller = MagicMock()
        self.controller.log = MagicMock()
        self.controller.event_stream = MagicMock()
        self.controller.set_agent_state_to = AsyncMock()
        self.controller._cleanup_action_context = MagicMock()
        self.controller.confirmation_service = MagicMock()
        self.controller.confirmation_service.handle_observation_for_pending_action = (
            AsyncMock()
        )
        self.controller.state = MagicMock()
        self.controller.state.agent_state = AgentState.RUNNING
        self.controller.state.budget_flag = None
        self.controller.state.metrics = MagicMock()
        self.controller.state.metrics.token_usages = []
        self.controller.state.metrics.accumulated_token_usage = MagicMock(
            prompt_tokens=0,
            completion_tokens=0,
        )
        self.controller.conversation_stats = MagicMock()
        self.controller.conversation_stats.get_combined_metrics.return_value = MagicMock(
            accumulated_cost=0.0,
            accumulated_token_usage=MagicMock(),
            max_budget_per_task=None,
        )
        self.controller.tool_pipeline = None

        self.context = MagicMock()
        self.context.get_controller.return_value = self.controller
        self.context.pop_action_context.return_value = None
        self.context.trigger_step = MagicMock()

        self.pending_service = PendingActionService(self.context, timeout=30.0)
        self.confirmation_service = MagicMock()
        self.confirmation_service.evaluate_action = AsyncMock()
        self.confirmation_service.handle_pending_confirmation = AsyncMock()
        self.action_service = ActionService(
            self.context, self.pending_service, self.confirmation_service
        )
        self.observation_service = ObservationService(self.context, self.pending_service)

    async def test_action_pending_observation_clear_single_step_chain(self):
        """Runnable action resolution should follow one pending-action lifecycle."""
        action = CmdRunAction(command="echo hello")
        action.id = 101
        action.source = EventSource.AGENT

        observation = CmdOutputObservation(
            content="hello",
            command="echo hello",
            metadata={"exit_code": 0},
        )
        observation.cause = 101

        with (
            patch.object(PendingActionService, "_schedule_watchdog", autospec=True),
            patch("backend.core.plugin.get_plugin_registry") as mock_registry,
        ):
            mock_registry.return_value.dispatch_action_post = AsyncMock(
                return_value=observation
            )

            await self.action_service.run(action, None)
            self.assertIs(self.pending_service.get(), action)

            await self.observation_service._handle_pending_action_observation(observation)

        self.assertIsNone(self.pending_service.get())
        self.confirmation_service.evaluate_action.assert_awaited_once_with(action)
        self.confirmation_service.handle_pending_confirmation.assert_awaited_once_with(
            action
        )
        self.controller.confirmation_service.handle_observation_for_pending_action.assert_awaited_once_with(
            observation, None
        )
        self.context.trigger_step.assert_called_once_with()
