"""Tests for EventRouterService finish handling."""

import unittest
from unittest.mock import AsyncMock, MagicMock

from backend.core.schemas import AgentState
from backend.ledger.action import PlaybookFinishAction
from backend.orchestration.services.event_router_service import EventRouterService


class TestFinishGuard(unittest.IsolatedAsyncioTestCase):
    """Test finish routing without heuristic file guards."""

    def setUp(self):
        self.mock_controller = MagicMock()
        self.mock_controller.state = MagicMock()
        self.mock_controller.state.start_id = 0
        self.mock_controller.state.history = []
        self.mock_controller.state.extra_data = {}
        self.mock_controller.event_stream = MagicMock()
        self.mock_controller.set_agent_state_to = AsyncMock()
        self.mock_controller.log_task_audit = AsyncMock()
        self.mock_controller.task_validation_service = MagicMock()
        self.mock_controller.task_validation_service.handle_finish = AsyncMock(
            return_value=True
        )
        self.mock_controller.get_agent_state = MagicMock(
            return_value=AgentState.RUNNING
        )
        self.mock_controller._first_user_message = MagicMock(return_value=None)

        self.service = EventRouterService(self.mock_controller)

    async def test_finish_calls_validation_service(self):
        action = PlaybookFinishAction(outputs={'result': 'done'})
        await self.service._handle_finish_action(action)
        self.mock_controller.task_validation_service.handle_finish.assert_awaited_once_with(
            action
        )
        self.mock_controller.set_agent_state_to.assert_called_once_with(
            AgentState.FINISHED
        )

    async def test_finish_allowed_when_validation_passes(self):
        action = PlaybookFinishAction(outputs={'result': 'done'})
        await self.service._handle_finish_action(action)
        self.mock_controller.set_agent_state_to.assert_called_once_with(
            AgentState.FINISHED
        )
        self.mock_controller.log_task_audit.assert_called_once_with(status='success')

    async def test_validation_failure_blocks_finish(self):
        action = PlaybookFinishAction(outputs={'result': 'done'})
        self.mock_controller.task_validation_service.handle_finish = AsyncMock(
            return_value=False
        )
        await self.service._handle_finish_action(action)
        self.mock_controller.set_agent_state_to.assert_not_called()
        self.mock_controller.log_task_audit.assert_not_called()


if __name__ == '__main__':
    unittest.main()
