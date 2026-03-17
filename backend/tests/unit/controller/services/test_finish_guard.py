"""Tests for EventRouterService INCOMPLETE_TASK finish guard.

When the agent calls finish() but not all task files have been created,
the guard should block the finish and emit an ErrorObservation with
error_id='INCOMPLETE_TASK'. The guard is bypassed when force_finish=True.
"""

import unittest
from unittest.mock import MagicMock, AsyncMock, patch

from backend.controller.services.event_router_service import EventRouterService
from backend.core.schemas import AgentState
from backend.events import EventSource
from backend.events.action import PlaybookFinishAction


class TestFinishGuard(unittest.IsolatedAsyncioTestCase):
    """Test INCOMPLETE_TASK finish guard logic."""

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

    async def test_finish_blocked_when_files_missing(self):
        """Finish should be blocked when task files are missing."""
        action = PlaybookFinishAction(outputs={"result": "done"})

        # Mock _get_missing_task_files to return missing files
        self.service._get_missing_task_files = MagicMock(  # type: ignore[method-assign]
            return_value={"src/app/page.tsx", "src/app/layout.tsx"}
        )

        await self.service._handle_finish_action(action)

        # Should NOT set state to finished
        self.mock_controller.set_agent_state_to.assert_not_called()
        # Should emit an error observation
        self.mock_controller.event_stream.add_event.assert_called_once()
        args, _ = self.mock_controller.event_stream.add_event.call_args
        error_obs = args[0]
        self.assertEqual(error_obs.error_id, "INCOMPLETE_TASK")
        self.assertIn("FINISH BLOCKED", error_obs.content)
        self.assertIn("src/app/page.tsx", error_obs.content)

    async def test_force_finish_bypasses_guard(self):
        """force_finish=True should bypass the missing files guard."""
        action = PlaybookFinishAction(
            outputs={"result": "done"},
        )
        action.force_finish = True

        # Even with missing files, should not check
        self.service._get_missing_task_files = MagicMock(
            return_value={"src/app/page.tsx"}
        )

        await self.service._handle_finish_action(action)

        # _get_missing_task_files should NOT be called
        self.service._get_missing_task_files.assert_not_called()
        # Should proceed to finish
        self.mock_controller.set_agent_state_to.assert_called_once_with(
            AgentState.FINISHED
        )

    async def test_finish_allowed_when_no_missing_files(self):
        """Finish allowed when all task files are created."""
        action = PlaybookFinishAction(outputs={"result": "done"})

        self.service._get_missing_task_files = MagicMock(return_value=set())  # type: ignore[method-assign]

        await self.service._handle_finish_action(action)

        # Should set state to finished
        self.mock_controller.set_agent_state_to.assert_called_once_with(
            AgentState.FINISHED
        )
        self.mock_controller.log_task_audit.assert_called_once_with(status="success")

    async def test_blocked_finish_does_not_log_audit(self):
        """Blocked finish should not log a success audit."""
        action = PlaybookFinishAction(outputs={"result": "done"})
        self.service._get_missing_task_files = MagicMock(  # type: ignore[method-assign]
            return_value={"src/missing.tsx"}
        )

        await self.service._handle_finish_action(action)

        self.mock_controller.log_task_audit.assert_not_called()

    async def test_error_observation_source_is_environment(self):
        """INCOMPLETE_TASK error should come from ENVIRONMENT source."""
        action = PlaybookFinishAction(outputs={"result": "done"})
        self.service._get_missing_task_files = MagicMock(  # type: ignore[method-assign]
            return_value={"src/page.tsx"}
        )

        await self.service._handle_finish_action(action)

        args, _ = self.mock_controller.event_stream.add_event.call_args
        source = args[1]
        self.assertEqual(source, EventSource.ENVIRONMENT)


if __name__ == "__main__":
    unittest.main()
