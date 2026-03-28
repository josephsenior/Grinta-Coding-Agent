"""Tests for EventRouterService."""

import unittest
from unittest.mock import MagicMock, AsyncMock, patch

from backend.orchestration.services.event_router_service import EventRouterService
from backend.core.schemas import AgentState
from backend.ledger import EventSource
from backend.ledger.action import (
    Action,
    ChangeAgentStateAction,
    MessageAction,
    PlaybookFinishAction,
    AgentRejectAction,
    TaskTrackingAction,
)
from backend.ledger.observation import Observation


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

    @patch("backend.core.plugin.get_plugin_registry")
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

    @patch("backend.core.plugin.get_plugin_registry")
    async def test_route_event_plugin_exception(self, mock_get_registry):
        """Test route_event handles plugin exceptions gracefully."""
        mock_registry = MagicMock()
        mock_registry.dispatch_event = AsyncMock(
            side_effect=RuntimeError("Plugin error")
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
            self.service, "_handle_action", new_callable=AsyncMock
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
        action = ChangeAgentStateAction(agent_state="paused")

        await self.service._handle_action(action)

        # Should change to PAUSED state
        self.mock_controller.set_agent_state_to.assert_called_once_with(
            AgentState.PAUSED
        )

    async def test_handle_action_change_state_invalid(self):
        """Test _handle_action handles invalid agent state gracefully."""
        action = ChangeAgentStateAction(agent_state="invalid_state")

        await self.service._handle_action(action)

        # Should log warning but not crash
        self.mock_controller.log.assert_called_once()
        self.mock_controller.set_agent_state_to.assert_not_called()

    async def test_handle_action_message_from_user(self):
        """Test _handle_action processes MessageAction from user."""
        action = MessageAction(content="Hello")
        action.source = EventSource.USER
        action.id = 123

        with patch(
            "backend.orchestration.services.event_router_service.RecallAction"
        ) as mock_recall:
            mock_recall_instance = MagicMock()
            mock_recall.return_value = mock_recall_instance

            await self.service._handle_action(action)

        # Should create and add recall action
        self.mock_controller.event_stream.add_event.assert_called_once()

    async def test_handle_action_message_from_agent_wait_response(self):
        """Test _handle_action sets awaiting input for agent message."""
        action = MessageAction(content="Question?")
        action.source = EventSource.AGENT
        action.wait_for_response = True

        await self.service._handle_action(action)

        # Should set state to awaiting user input
        self.mock_controller.set_agent_state_to.assert_called_once_with(
            AgentState.AWAITING_USER_INPUT
        )

    async def test_handle_action_message_from_agent_no_wait(self):
        """Test _handle_action skips state change when no wait."""
        action = MessageAction(content="Statement")
        action.source = EventSource.AGENT
        action.wait_for_response = False

        await self.service._handle_action(action)

        # Should not change state
        self.mock_controller.set_agent_state_to.assert_not_called()

    @patch.dict("os.environ", {"LOG_ALL_EVENTS": "true"})
    async def test_handle_message_action_log_all_events(self):
        """Test _handle_message_action uses info level when LOG_ALL_EVENTS=true."""
        action = MessageAction(content="Test")
        action.source = EventSource.USER
        action.id = 456

        with patch("backend.orchestration.services.event_router_service.RecallAction"):
            await self.service._handle_message_action(action)

        # Should log at info level
        call_args = self.mock_controller.log.call_args[0]
        self.assertEqual(call_args[0], "info")

    async def test_handle_message_action_first_user_message(self):
        """Test _handle_message_action uses WORKSPACE_CONTEXT for first message."""
        action = MessageAction(content="First message")
        action.source = EventSource.USER
        action.id = 1

        # Implementation determines the first user message by scanning the event stream.
        self.mock_controller.event_stream.search_events.return_value = [action]

        with patch(
            "backend.orchestration.services.event_router_service.RecallAction"
        ) as mock_recall:
            with patch(
                "backend.orchestration.services.event_router_service.RecallType"
            ) as mock_recall_type:
                mock_recall_type.WORKSPACE_CONTEXT = "workspace"
                mock_recall_type.KNOWLEDGE = "knowledge"

                await self.service._handle_message_action(action)

                # Should use WORKSPACE_CONTEXT recall type
                call_kwargs = mock_recall.call_args[1]
                self.assertEqual(call_kwargs["recall_type"], "workspace")

    async def test_handle_message_action_subsequent_message(self):
        """Test _handle_message_action uses KNOWLEDGE for subsequent messages."""
        action = MessageAction(content="Second message")
        action.source = EventSource.USER
        action.id = 2

        first_action = MessageAction(content="First message")
        first_action.source = EventSource.USER
        first_action.id = 1

        # Implementation determines the first user message by scanning the event stream.
        self.mock_controller.event_stream.search_events.return_value = [first_action, action]

        with patch(
            "backend.orchestration.services.event_router_service.RecallAction"
        ) as mock_recall:
            with patch(
                "backend.orchestration.services.event_router_service.RecallType"
            ) as mock_recall_type:
                mock_recall_type.WORKSPACE_CONTEXT = "workspace"
                mock_recall_type.KNOWLEDGE = "knowledge"

                await self.service._handle_message_action(action)

                # Should use KNOWLEDGE recall type
                call_kwargs = mock_recall.call_args[1]
                self.assertEqual(call_kwargs["recall_type"], "knowledge")

    async def test_handle_message_action_user_not_running(self):
        """Test _handle_message_action sets state to running if not already."""
        action = MessageAction(content="Message")
        action.source = EventSource.USER
        action.id = 789

        self.mock_controller.get_agent_state.return_value = AgentState.PAUSED

        with patch("backend.orchestration.services.event_router_service.RecallAction"):
            await self.service._handle_message_action(action)

        # Should set state to running
        self.mock_controller.set_agent_state_to.assert_called_once_with(
            AgentState.RUNNING
        )

    async def test_handle_task_tracking_action_uses_canonical_plan_normalization(self):
        """Live plan updates should use the same normalization as persisted state reloads."""
        action = TaskTrackingAction(
            command="update",
            task_list=[
                {
                    "title": "Top level",
                    "status": "unknown",
                    "notes": "legacy note",
                    "subtasks": [{"title": "Nested child", "status": "completed"}],
                }
            ],
        )

        await self.service._handle_task_tracking_action(action)

        plan = self.mock_controller.state.plan
        self.assertEqual(plan.steps[0].id, "step-1")
        self.assertEqual(plan.steps[0].description, "Top level")
        self.assertEqual(plan.steps[0].status, "pending")
        self.assertEqual(plan.steps[0].result, "legacy note")
        self.assertEqual(plan.steps[0].subtasks[0].id, "step-1")
        self.assertEqual(plan.steps[0].subtasks[0].description, "Nested child")
        self.assertEqual(plan.steps[0].subtasks[0].status, "completed")

    async def test_handle_finish_action_success(self):
        """Test _handle_finish_action marks task as finished."""
        action = PlaybookFinishAction(outputs={"result": "success"})

        await self.service._handle_finish_action(action)

        # Should set outputs
        self.mock_controller.state.set_outputs.assert_called_once_with(
            {"result": "success"}, source="EventRouterService.finish"
        )

        # Should set state to finished
        self.mock_controller.set_agent_state_to.assert_called_once_with(
            AgentState.FINISHED
        )

        # Should log audit
        self.mock_controller.log_task_audit.assert_called_once_with(status="success")

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
        action = AgentRejectAction(outputs={"reason": "rejected"})

        await self.service._handle_reject_action(action)

        # Should set outputs
        self.mock_controller.state.set_outputs.assert_called_once_with(
            {"reason": "rejected"}, source="EventRouterService.reject"
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

    @patch("backend.utils.async_utils.run_or_schedule")
    async def test_handle_delegate_task_action(self, mock_run_schedule):
        """Test _handle_delegate_task_action schedules worker execution."""
        from backend.ledger.action.agent import DelegateTaskAction

        action = DelegateTaskAction(
            task_description="Build a new feature", files=["main.py"]
        )

        await self.service._handle_delegate_task_action(action)

        # Should schedule the background task
        mock_run_schedule.assert_called_once()


    # ── critic wiring ─────────────────────────────────────────────────────

    async def test_run_critics_logs_results(self):
        """Test _run_critics logs a score line for each critic and stores scores in extra_data."""
        with patch("backend.governance.AgentFinishedCritic.evaluate") as m_fin, \
             patch("backend.governance.BudgetCritic.evaluate") as m_bud, \
             patch("backend.governance.SuitePassCritic.evaluate") as m_suite:
            from backend.governance import CriticResult
            m_fin.return_value = CriticResult(score=1.0, message="Agent finished.")
            m_bud.return_value = CriticResult(score=0.8, message="acceptable usage")
            m_suite.return_value = CriticResult(score=1.0, message="All tests pass.")

            await self.service._run_critics()

        # One log call per critic
        assert self.mock_controller.log.call_count == 3
        logged_messages = [call.args[1] for call in self.mock_controller.log.call_args_list]
        assert any("AgentFinishedCritic" in m for m in logged_messages)
        assert any("BudgetCritic" in m for m in logged_messages)
        assert any("SuitePassCritic" in m for m in logged_messages)

        # Scores must be persisted in state.extra_data
        scores = self.mock_controller.state.extra_data["critic_scores"]
        assert scores["AgentFinishedCritic"]["score"] == 1.0
        assert scores["BudgetCritic"]["score"] == 0.8
        assert scores["SuitePassCritic"]["score"] == 1.0

    async def test_run_critics_tolerates_exceptions(self):
        """A crashing critic must not prevent the others from running."""
        with patch("backend.governance.AgentFinishedCritic.evaluate",
                   side_effect=RuntimeError("boom")):
            with patch("backend.governance.BudgetCritic.evaluate") as m_bud, \
                 patch("backend.governance.SuitePassCritic.evaluate") as m_suite:
                from backend.governance import CriticResult
                m_bud.return_value = CriticResult(score=1.0, message="ok")
                m_suite.return_value = CriticResult(score=1.0, message="ok")

                await self.service._run_critics()  # must not raise

        # warning for the bad critic, info for the other two
        levels = [call.args[0] for call in self.mock_controller.log.call_args_list]
        assert "warning" in levels

    async def test_handle_finish_action_calls_run_critics(self):
        """_handle_finish_action must invoke critics after audit log."""
        action = PlaybookFinishAction(outputs={})
        with patch.object(self.service, "_run_critics", new_callable=AsyncMock) as m:
            await self.service._handle_finish_action(action)
        m.assert_called_once()

    async def test_run_critics_skipped_when_disabled(self):
        """When FORGE_ENABLE_CRITICS=false, critics must not run and no scores are stored."""
        import os
        with patch.dict(os.environ, {"FORGE_ENABLE_CRITICS": "false"}):
            with patch("backend.governance.AgentFinishedCritic.evaluate") as m_fin, \
                 patch("backend.governance.BudgetCritic.evaluate") as m_bud, \
                 patch("backend.governance.SuitePassCritic.evaluate") as m_suite:
                await self.service._run_critics()
                m_fin.assert_not_called()
                m_bud.assert_not_called()
                m_suite.assert_not_called()

        # No critic_scores written to extra_data
        assert "critic_scores" not in self.mock_controller.state.extra_data


if __name__ == "__main__":
    unittest.main()
