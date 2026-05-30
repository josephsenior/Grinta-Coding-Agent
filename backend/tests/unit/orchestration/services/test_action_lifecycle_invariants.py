"""Integration-adjacent lifecycle invariants across controller services."""

from __future__ import annotations

import unittest
from contextlib import suppress
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, MagicMock, patch

from backend.core.schemas import AgentState
from backend.ledger import EventSource
from backend.ledger.action import CmdRunAction
from backend.ledger.observation.commands import CmdOutputObservation
from backend.ledger.stream import EventStream, EventStreamSubscriber
from backend.orchestration.services.action_service import ActionService
from backend.orchestration.services.observation_service import ObservationService
from backend.orchestration.services.pending_action_service import PendingActionService
from backend.persistence.local_file_store import LocalFileStore


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
        self.controller.conversation_stats.get_combined_metrics.return_value = (
            MagicMock(
                accumulated_cost=0.0,
                accumulated_token_usage=MagicMock(),
                max_budget_per_task=None,
            )
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
        self.observation_service = ObservationService(
            self.context, self.pending_service
        )

    async def test_action_pending_observation_clear_single_step_chain(self):
        """Runnable action resolution should follow one pending-action lifecycle."""
        action = CmdRunAction(command='echo hello')
        action.id = 101
        action.source = EventSource.AGENT

        observation = CmdOutputObservation(
            content='hello',
            command='echo hello',
            metadata={'exit_code': 0},
        )
        observation.cause = 101

        with (
            patch.object(PendingActionService, '_schedule_watchdog', autospec=True),
            patch('backend.core.plugin.get_plugin_registry') as mock_registry,
        ):
            mock_registry.return_value.dispatch_action_post = AsyncMock(
                return_value=observation
            )

            await self.action_service.run(action, None)
            self.assertIs(self.pending_service.get(), action)

            await self.observation_service._handle_pending_action_observation(
                observation
            )

        self.assertIsNone(self.pending_service.get())
        self.confirmation_service.evaluate_action.assert_awaited_once_with(action)
        self.confirmation_service.handle_pending_confirmation.assert_awaited_once_with(
            action
        )
        self.controller.confirmation_service.handle_observation_for_pending_action.assert_awaited_once_with(
            observation, None
        )
        self.context.trigger_step.assert_called_once_with()

    async def test_real_event_stream_arms_pending_before_runtime_dispatch(self):
        """Runtime can emit an observation during action dispatch without stalling."""
        tmpdir = TemporaryDirectory()
        stream = EventStream(
            sid='pending-race-test',
            file_store=LocalFileStore(tmpdir.name),
            worker_count=0,
        )
        try:
            self.controller.event_stream = stream
            self.context.emit_event.side_effect = (
                lambda event, source: stream.add_event(event, source)
            )

            action = CmdRunAction(command='echo hello')
            action.source = EventSource.AGENT
            pending_was_armed_before_runtime: list[bool] = []
            clean_metrics = MagicMock()
            clean_metrics.get.return_value = {}
            metrics = MagicMock(
                accumulated_cost=0.0,
                accumulated_token_usage=MagicMock(),
                max_budget_per_task=None,
            )
            metrics.copy.return_value = clean_metrics
            self.controller.conversation_stats.get_combined_metrics.return_value = (
                metrics
            )

            def runtime_callback(event):
                if not isinstance(event, CmdRunAction):
                    return
                pending_was_armed_before_runtime.append(
                    self.pending_service.peek_for_cause(event.id) is not None
                )
                observation = CmdOutputObservation(
                    content='hello',
                    command='echo hello',
                    metadata={'exit_code': 0},
                )
                observation.cause = event.id
                stream.add_event(observation, EventSource.ENVIRONMENT)

            stream.subscribe(
                EventStreamSubscriber.RUNTIME,
                runtime_callback,
                'runtime-race',
            )
            stream.subscribe(
                EventStreamSubscriber.MAIN,
                lambda event: None,
                'controller-placeholder',
            )

            with patch.object(
                PendingActionService, '_schedule_watchdog', autospec=True
            ):
                await self.action_service.run(action, None)

            self.assertEqual(pending_was_armed_before_runtime, [True])
            self.assertIsNotNone(self.pending_service.peek_for_cause(action.id))
        finally:
            with suppress(Exception):
                stream.close()
            with suppress(Exception):
                tmpdir.cleanup()

    async def test_restored_state_late_observation_does_not_duplicate_advancement(self):
        """A restored controller with no pending action must ignore stale late observations."""
        self.controller.state.resume_state = AgentState.PAUSED
        self.controller.state.agent_state = AgentState.PAUSED

        late_observation = CmdOutputObservation(
            content='late result',
            command='echo hello',
            metadata={'exit_code': 0},
        )
        late_observation.cause = 101

        with patch('backend.core.plugin.get_plugin_registry'):
            await self.observation_service._handle_pending_action_observation(
                late_observation
            )

        self.assertIsNone(self.pending_service.get())
        self.context.trigger_step.assert_not_called()
        self.controller.confirmation_service.handle_observation_for_pending_action.assert_not_awaited()
