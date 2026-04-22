"""Tests for EventRouterService."""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from backend.core.schemas import AgentState
from backend.ledger import EventSource
from backend.ledger.action import (
    Action,
    AgentRejectAction,
    ChangeAgentStateAction,
    CmdRunAction,
    FileReadAction,
    MessageAction,
    PlaybookFinishAction,
    SignalProgressAction,
    TaskTrackingAction,
)
from backend.ledger.observation import ErrorObservation, Observation
from backend.ledger.observation.agent import AgentThinkObservation
from backend.ledger.tool import ToolCallMetadata
from backend.orchestration.services.event_router_service import (
    EventRouterService,
    _build_delegate_progress_observation,
    _summarize_delegate_worker_event,
)


class TestEventRouterService(unittest.IsolatedAsyncioTestCase):
    """Test EventRouterService event routing logic."""

    def setUp(self):
        """Create mock controller for testing."""
        self.mock_controller = MagicMock()
        self.mock_controller.state_tracker = MagicMock()
        self.mock_controller.log = MagicMock()
        self.mock_controller.set_agent_state_to = AsyncMock()
        self.mock_controller.log_task_audit = AsyncMock()
        self.mock_controller.task_validation_service = MagicMock()
        self.mock_controller.task_validation_service.handle_finish = AsyncMock(
            return_value=True
        )
        self.mock_controller.observation_service = MagicMock()
        self.mock_controller.observation_service.handle_observation = AsyncMock()
        self.mock_controller.state = MagicMock()
        self.mock_controller.state.start_id = 0
        self.mock_controller.state.history = []
        self.mock_controller.state.extra_data = {}
        self.mock_controller.event_stream = MagicMock()
        self.mock_controller.get_agent_state = MagicMock(
            return_value=AgentState.RUNNING
        )
        self.mock_controller._first_user_message = MagicMock(return_value=None)

        self.service = EventRouterService(self.mock_controller)

    async def test_route_event_hidden(self):
        """Test route_event skips hidden events."""
        mock_event = MagicMock()
        mock_event.hidden = True

        await self.service.route_event(mock_event)

        # Should not add to history for hidden events
        self.mock_controller.state_tracker.add_history.assert_not_called()

    @patch('backend.core.plugin.get_plugin_registry')
    async def test_route_event_plugin_hook(self, mock_get_registry):
        """Test route_event fires plugin hook."""
        mock_registry = MagicMock()
        mock_registry.dispatch_event = AsyncMock()
        mock_get_registry.return_value = mock_registry

        mock_event = MagicMock(spec=Action)
        mock_event.hidden = False

        await self.service.route_event(mock_event)

        # Should dispatch to plugins
        mock_registry.dispatch_event.assert_called_once_with(mock_event)

    @patch('backend.core.plugin.get_plugin_registry')
    async def test_route_event_plugin_exception(self, mock_get_registry):
        """Test route_event handles plugin exceptions gracefully."""
        mock_registry = MagicMock()
        mock_registry.dispatch_event = AsyncMock(
            side_effect=RuntimeError('Plugin error')
        )
        mock_get_registry.return_value = mock_registry

        mock_event = MagicMock(spec=Action)
        mock_event.hidden = False

        # Should not raise exception
        await self.service.route_event(mock_event)

        # Should still add to history
        self.mock_controller.state_tracker.add_history.assert_called_once_with(
            mock_event
        )

    async def test_route_event_action(self):
        """Test route_event delegates actions to _handle_action."""
        mock_action = MagicMock(spec=Action)
        mock_action.hidden = False

        with patch.object(
            self.service, '_handle_action', new_callable=AsyncMock
        ) as mock_handle:
            await self.service.route_event(mock_action)

        mock_handle.assert_called_once_with(mock_action)

    async def test_route_event_observation(self):
        """Test route_event delegates observations to observation service."""
        mock_observation = MagicMock(spec=Observation)
        mock_observation.hidden = False

        await self.service.route_event(mock_observation)

        self.mock_controller.observation_service.handle_observation.assert_called_once_with(
            mock_observation
        )

    async def test_handle_action_change_state(self):
        """Test _handle_action processes ChangeAgentStateAction."""
        action = ChangeAgentStateAction(agent_state='paused')

        await self.service._handle_action(action)

        # Should change to PAUSED state
        self.mock_controller.set_agent_state_to.assert_called_once_with(
            AgentState.PAUSED
        )

    async def test_handle_action_change_state_invalid(self):
        """Test _handle_action handles invalid agent state gracefully."""
        action = ChangeAgentStateAction(agent_state='invalid_state')

        await self.service._handle_action(action)

        # Should log warning but not crash
        self.mock_controller.log.assert_called_once()
        self.mock_controller.set_agent_state_to.assert_not_called()

    async def test_handle_action_message_from_user(self):
        """Test _handle_action processes MessageAction from user."""
        action = MessageAction(content='Hello')
        action.source = EventSource.USER
        action.id = 123

        with patch(
            'backend.orchestration.services.event_router_service.RecallAction'
        ) as mock_recall:
            mock_recall_instance = MagicMock()
            mock_recall.return_value = mock_recall_instance

            await self.service._handle_action(action)

        # Should create and add recall action
        self.mock_controller.event_stream.add_event.assert_called_once()

    async def test_handle_action_message_from_agent_wait_response(self):
        """Test _handle_action sets awaiting input for agent message."""
        action = MessageAction(content='Question?')
        action.source = EventSource.AGENT
        action.wait_for_response = True

        await self.service._handle_action(action)

        # Should set state to awaiting user input
        self.mock_controller.set_agent_state_to.assert_called_once_with(
            AgentState.AWAITING_USER_INPUT
        )

    async def test_handle_action_message_from_agent_no_wait(self):
        """Test _handle_action skips state change when no wait."""
        action = MessageAction(content='Statement')
        action.source = EventSource.AGENT
        action.wait_for_response = False

        await self.service._handle_action(action)

        # Should not change state
        self.mock_controller.set_agent_state_to.assert_not_called()

    async def test_handle_action_message_from_agent_blocks_incomplete_checkpoint_handoff(
        self,
    ):
        checkpoint_obs = AgentThinkObservation(content='Your thought has been logged.')
        checkpoint_obs.tool_result = {
            'tool': 'checkpoint',
            'ok': True,
            'status': 'saved',
            'next_best_action': 'Continue with the next planned step.',
        }
        checkpoint_obs.tool_call_metadata = ToolCallMetadata(
            function_name='checkpoint',
            tool_call_id='call_checkpoint',
            model_response={'id': 'resp_checkpoint'},
            total_calls_in_response=1,
        )
        action = MessageAction(content='Checkpoint saved.')
        action.source = EventSource.AGENT
        action.wait_for_response = True
        self.mock_controller.state.history = [checkpoint_obs, action]

        await self.service._handle_action(action)

        self.mock_controller.set_agent_state_to.assert_not_called()
        self.mock_controller.event_stream.add_event.assert_called_once()
        emitted = self.mock_controller.event_stream.add_event.call_args[0][0]
        self.assertIsInstance(emitted, ErrorObservation)
        self.assertEqual(emitted.error_id, 'CHECKPOINT_FLOW_INCOMPLETE')
        self.assertIn('task_tracker update', emitted.content)
        self.assertIn('finish', emitted.content)

    async def test_handle_action_message_from_agent_allows_checkpoint_completion_handoff(
        self,
    ):
        checkpoint_obs = AgentThinkObservation(content='Your thought has been logged.')
        checkpoint_obs.tool_result = {
            'tool': 'checkpoint',
            'ok': True,
            'status': 'saved',
            'next_best_action': 'Continue with the next planned step.',
        }
        checkpoint_obs.tool_call_metadata = ToolCallMetadata(
            function_name='checkpoint',
            tool_call_id='call_checkpoint',
            model_response={'id': 'resp_checkpoint'},
            total_calls_in_response=1,
        )
        action = MessageAction(
            content='Implementation is complete. Next steps: 1. run the focused tests 2. commit if the results are clean.'
        )
        action.source = EventSource.AGENT
        action.wait_for_response = True
        self.mock_controller.state.history = [checkpoint_obs, action]

        await self.service._handle_action(action)

        self.mock_controller.set_agent_state_to.assert_called_once_with(
            AgentState.AWAITING_USER_INPUT
        )
        self.mock_controller.event_stream.add_event.assert_not_called()

    async def test_handle_action_message_from_agent_blocks_incomplete_revert_handoff(
        self,
    ):
        revert_obs = AgentThinkObservation(content='Your thought has been logged.')
        revert_obs.tool_result = {
            'tool': 'revert_to_checkpoint',
            'ok': True,
            'status': 'reverted',
            'next_best_action': 'Continue from the restored checkpoint state.',
        }
        revert_obs.tool_call_metadata = ToolCallMetadata(
            function_name='revert_to_checkpoint',
            tool_call_id='call_revert',
            model_response={'id': 'resp_revert'},
            total_calls_in_response=1,
        )
        action = MessageAction(content='Rollback completed.')
        action.source = EventSource.AGENT
        action.wait_for_response = True
        self.mock_controller.state.history = [revert_obs, action]

        await self.service._handle_action(action)

        self.mock_controller.set_agent_state_to.assert_not_called()
        self.mock_controller.event_stream.add_event.assert_called_once()
        emitted = self.mock_controller.event_stream.add_event.call_args[0][0]
        self.assertIsInstance(emitted, ErrorObservation)
        self.assertEqual(emitted.error_id, 'CHECKPOINT_FLOW_INCOMPLETE')
        self.assertIn(
            'revert_to_checkpoint is an intermediate control tool', emitted.content
        )

    @patch.dict('os.environ', {'LOG_ALL_EVENTS': 'true'})
    async def test_handle_message_action_log_all_events(self):
        """Test _handle_message_action uses info level when LOG_ALL_EVENTS=true."""
        action = MessageAction(content='Test')
        action.source = EventSource.USER
        action.id = 456

        with patch('backend.orchestration.services.event_router_service.RecallAction'):
            await self.service._handle_message_action(action)

        # Should log at info level
        call_args = self.mock_controller.log.call_args[0]
        self.assertEqual(call_args[0], 'info')

    async def test_handle_message_action_first_user_message(self):
        """Test _handle_message_action uses WORKSPACE_CONTEXT for first message."""
        action = MessageAction(content='First message')
        action.source = EventSource.USER
        action.id = 1

        # Implementation determines the first user message by scanning the event stream.
        self.mock_controller.event_stream.search_events.return_value = [action]

        with patch(
            'backend.orchestration.services.event_router_service.RecallAction'
        ) as mock_recall:
            with patch(
                'backend.orchestration.services.event_router_service.RecallType'
            ) as mock_recall_type:
                mock_recall_type.WORKSPACE_CONTEXT = 'workspace'
                mock_recall_type.KNOWLEDGE = 'knowledge'

                await self.service._handle_message_action(action)

                # Should use WORKSPACE_CONTEXT recall type
                call_kwargs = mock_recall.call_args[1]
                self.assertEqual(call_kwargs['recall_type'], 'workspace')

    async def test_handle_message_action_subsequent_message(self):
        """Test _handle_message_action uses KNOWLEDGE for subsequent messages."""
        action = MessageAction(content='Second message')
        action.source = EventSource.USER
        action.id = 2

        first_action = MessageAction(content='First message')
        first_action.source = EventSource.USER
        first_action.id = 1

        # Implementation determines the first user message by scanning the event stream.
        self.mock_controller.event_stream.search_events.return_value = [
            first_action,
            action,
        ]

        with patch(
            'backend.orchestration.services.event_router_service.RecallAction'
        ) as mock_recall:
            with patch(
                'backend.orchestration.services.event_router_service.RecallType'
            ) as mock_recall_type:
                mock_recall_type.WORKSPACE_CONTEXT = 'workspace'
                mock_recall_type.KNOWLEDGE = 'knowledge'

                await self.service._handle_message_action(action)

                # Should use KNOWLEDGE recall type
                call_kwargs = mock_recall.call_args[1]
                self.assertEqual(call_kwargs['recall_type'], 'knowledge')

    async def test_handle_message_action_user_not_running(self):
        """Test _handle_message_action sets state to running if not already."""
        action = MessageAction(content='Message')
        action.source = EventSource.USER
        action.id = 789

        self.mock_controller.get_agent_state.return_value = AgentState.PAUSED

        with patch('backend.orchestration.services.event_router_service.RecallAction'):
            await self.service._handle_message_action(action)

        # Should set state to running
        self.mock_controller.set_agent_state_to.assert_called_once_with(
            AgentState.RUNNING
        )

    async def test_handle_task_tracking_action_uses_canonical_plan_payloads(self):
        """Live plan updates should keep the canonical task payload shape intact."""
        action = TaskTrackingAction(
            command='update',
            task_list=[
                {
                    'description': 'Top level',
                    'status': 'doing',
                    'result': 'progress note',
                    'subtasks': [{'description': 'Nested child', 'status': 'done'}],
                }
            ],
        )

        await self.service._handle_task_tracking_action(action)

        plan = self.mock_controller.state.plan
        self.assertEqual(plan.steps[0].id, 'step-1')
        self.assertEqual(plan.steps[0].description, 'Top level')
        self.assertEqual(plan.steps[0].status, 'doing')
        self.assertEqual(plan.steps[0].result, 'progress note')
        self.assertEqual(plan.steps[0].subtasks[0].id, 'step-1')
        self.assertEqual(plan.steps[0].subtasks[0].description, 'Nested child')
        self.assertEqual(plan.steps[0].subtasks[0].status, 'done')

    async def test_handle_finish_action_success(self):
        """Test _handle_finish_action marks task as finished."""
        action = PlaybookFinishAction(outputs={'result': 'success'})

        await self.service._handle_finish_action(action)

        # Should set outputs
        self.mock_controller.state.set_outputs.assert_called_once_with(
            {'result': 'success'}, source='EventRouterService.finish'
        )

        # Should set state to finished
        self.mock_controller.set_agent_state_to.assert_called_once_with(
            AgentState.FINISHED
        )

        # Should log audit
        self.mock_controller.log_task_audit.assert_called_once_with(status='success')

    async def test_handle_finish_action_validation_fails(self):
        """Test _handle_finish_action skips finish when validation fails."""
        action = PlaybookFinishAction(outputs={})

        self.mock_controller.task_validation_service.handle_finish = AsyncMock(
            return_value=False
        )

        await self.service._handle_finish_action(action)

        # Should not set state or outputs
        self.mock_controller.state.set_outputs.assert_not_called()
        self.mock_controller.set_agent_state_to.assert_not_called()

    async def test_handle_reject_action(self):
        """Test _handle_reject_action marks task as rejected."""
        action = AgentRejectAction(outputs={'reason': 'rejected'})

        await self.service._handle_reject_action(action)

        # Should set outputs
        self.mock_controller.state.set_outputs.assert_called_once_with(
            {'reason': 'rejected'}, source='EventRouterService.reject'
        )

        # Should set state to rejected
        self.mock_controller.set_agent_state_to.assert_called_once_with(
            AgentState.REJECTED
        )

    async def test_handle_observation(self):
        """Test _handle_observation delegates to observation service."""
        mock_observation = MagicMock(spec=Observation)

        await self.service._handle_observation(mock_observation)

        self.mock_controller.observation_service.handle_observation.assert_called_once_with(
            mock_observation
        )

    @patch('backend.utils.async_utils.run_or_schedule')
    async def test_handle_delegate_task_action(self, mock_run_schedule):
        """Test _handle_delegate_task_action schedules worker execution."""
        from backend.ledger.action.agent import DelegateTaskAction

        action = DelegateTaskAction(
            task_description='Build a new feature', files=['main.py']
        )

        await self.service._handle_delegate_task_action(action)

        # Should schedule the background task
        mock_run_schedule.assert_called_once()
        scheduled = mock_run_schedule.call_args.args[0]
        scheduled.close()

    async def test_delegate_workers_use_inline_event_delivery(self):
        """Delegated worker streams must use inline delivery and _step_inner for execution."""
        from backend.ledger.action.agent import DelegateTaskAction

        action = DelegateTaskAction(task_description='Build delegated artifact')
        action.id = 123

        # Parent controller must not auto-create runtime (MagicMock default)
        # so the runtime bridge code is skipped in this test.
        self.mock_controller.runtime = None

        self.mock_controller.config = SimpleNamespace(
            sid='parent-session',
            file_store=MagicMock(),
            user_id='user-1',
            agent_configs={},
            agent_to_llm_config={},
            iteration_delta=1,
            budget_per_task_delta=None,
            security_analyzer=None,
            pending_action_timeout=1.0,
        )
        self.mock_controller.agent = SimpleNamespace(
            config=None,
            llm_registry=MagicMock(),
        )

        scheduled: list = []

        def _capture(coro):
            scheduled.append(coro)

        class _FakeWorkerAgent:
            def __init__(self, config, llm_registry):
                self.config = config
                self.llm_registry = llm_registry
                self.blackboard = None
                self.tools = []
                self.planner = SimpleNamespace(build_toolset=lambda: [])

        step_inner_called = False

        class _FakeWorkerController:
            def __init__(self, config):
                self.config = config
                self.event_stream = config.event_stream
                self.state = SimpleNamespace(outputs={'result': 'ok'})
                self._states = iter(
                    [AgentState.RUNNING, AgentState.FINISHED, AgentState.FINISHED]
                )

            async def set_agent_state_to(self, state):
                return None

            async def _step_inner(self):
                nonlocal step_inner_called
                step_inner_called = True

            def get_agent_state(self):
                return next(self._states)

            async def close(self, set_stop_state=False):
                return None

        with patch('backend.utils.async_utils.run_or_schedule', side_effect=_capture):
            with patch(
                'backend.orchestration.services.event_router_service.EventStream'
            ) as mock_event_stream:
                worker_stream = MagicMock()
                mock_event_stream.return_value = worker_stream
                with patch(
                    'backend.orchestration.agent.Agent.get_cls',
                    return_value=_FakeWorkerAgent,
                ):
                    with patch(
                        'backend.orchestration.conversation_stats.ConversationStats',
                        return_value=MagicMock(),
                    ):
                        with patch(
                            'backend.orchestration.session_orchestrator.SessionOrchestrator',
                            _FakeWorkerController,
                        ):
                            await self.service._handle_delegate_task_action(action)
                            self.assertEqual(len(scheduled), 1)
                            await scheduled[0]

                # Worker stream must use inline delivery
                mock_event_stream.assert_called_once()
                self.assertEqual(mock_event_stream.call_args.kwargs['worker_count'], 0)
                # Worker loop must call _step_inner directly
                self.assertTrue(step_inner_called)

    async def test_handle_finish_action_calls_run_critics(self):
        """_handle_finish_action must invoke critics after audit log."""
        action = PlaybookFinishAction(outputs={})
        with patch.object(self.service, '_run_critics', new_callable=AsyncMock) as m:
            await self.service._handle_finish_action(action)
        m.assert_called_once()

    def test_summarize_delegate_worker_event_for_tool_actions(self):
        read_action = FileReadAction(path='src/main.py')
        assert _summarize_delegate_worker_event(read_action) == (
            'running',
            'Viewed src/main.py',
        )

        cmd_action = CmdRunAction(
            command='pytest -q', display_label='Running tests for worker'
        )
        assert _summarize_delegate_worker_event(cmd_action) == (
            'running',
            'Ran Running tests for worker',
        )

        signal_action = SignalProgressAction(progress_note='Halfway through test setup')
        assert _summarize_delegate_worker_event(signal_action) == (
            'running',
            'Halfway through test setup',
        )

    def test_build_delegate_progress_observation_is_hidden(self):
        obs = _build_delegate_progress_observation(
            worker_id='worker-1',
            worker_label='Worker 1',
            task_description='Write integration tests',
            status='running',
            detail='Viewed requirements.txt',
            order=1,
        )

        assert obs.hidden is True
        assert obs.status_type == 'delegate_progress'
        assert obs.extras['worker_id'] == 'worker-1'
        assert obs.extras['worker_status'] == 'running'
        assert 'Viewed requirements.txt' in obs.content


if __name__ == '__main__':
    unittest.main()
