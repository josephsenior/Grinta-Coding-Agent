"""Tests for TaskValidationService."""

import unittest
from unittest.mock import MagicMock, AsyncMock, patch

from backend.controller.services.task_validation_service import TaskValidationService
from backend.core.schemas import AgentState
from backend.events.action.agent import PlaybookFinishAction


class TestTaskValidationService(unittest.IsolatedAsyncioTestCase):
    """Test TaskValidationService task validation logic."""

    def setUp(self):
        """Create mock context for testing."""
        self.mock_context = MagicMock()
        self.mock_controller = MagicMock()
        self.mock_controller.state = MagicMock()
        self.mock_controller.state.agent_state = AgentState.RUNNING
        self.mock_controller.event_stream = MagicMock()
        self.mock_controller.set_agent_state_to = AsyncMock()
        self.mock_controller._get_initial_task = MagicMock()
        self.mock_context.get_controller.return_value = self.mock_controller

        self.service = TaskValidationService(self.mock_context)

    async def test_handle_finish_no_validator(self):
        """Test handle_finish proceeds when no validator configured."""
        action = PlaybookFinishAction(outputs={})

        self.mock_controller.task_validator = None

        result = await self.service.handle_finish(action)

        # Should return True to proceed with finish
        self.assertTrue(result)

    async def test_handle_finish_force_finish(self):
        """Test handle_finish skips validation when force_finish is True."""
        action = PlaybookFinishAction(outputs={})
        action.force_finish = True

        mock_validator = MagicMock()
        self.mock_controller.task_validator = mock_validator

        result = await self.service.handle_finish(action)

        # Should return True without validating
        self.assertTrue(result)
        mock_validator.validate_completion.assert_not_called()

    async def test_handle_finish_validation_passed(self):
        """Test handle_finish proceeds when validation passes."""
        action = PlaybookFinishAction(outputs={})

        mock_task = MagicMock()
        self.mock_controller._get_initial_task.return_value = mock_task

        mock_validation = MagicMock()
        mock_validation.passed = True
        mock_validation.reason = "All requirements met"

        mock_validator = MagicMock()
        mock_validator.validate_completion = AsyncMock(return_value=mock_validation)
        self.mock_controller.task_validator = mock_validator

        with patch(
            "backend.controller.services.task_validation_service.logger"
        ) as mock_logger:
            result = await self.service.handle_finish(action)

        # Should return True
        self.assertTrue(result)

        # Should validate
        mock_validator.validate_completion.assert_called_once_with(
            mock_task, self.mock_controller.state
        )

        # Should log success
        mock_logger.info.assert_called()

    async def test_handle_finish_validation_failed(self):
        """Test handle_finish handles validation failure."""
        action = PlaybookFinishAction(outputs={})

        mock_task = MagicMock()
        self.mock_controller._get_initial_task.return_value = mock_task

        mock_validation = MagicMock()
        mock_validation.passed = False
        mock_validation.reason = "Missing documentation"
        mock_validation.confidence = 0.85
        mock_validation.missing_items = ["README.md", "tests"]
        mock_validation.suggestions = ["Add README", "Write tests"]

        mock_validator = MagicMock()
        mock_validator.validate_completion = AsyncMock(return_value=mock_validation)
        self.mock_controller.task_validator = mock_validator

        with patch("backend.controller.services.task_validation_service.logger"):
            result = await self.service.handle_finish(action)

        # Should return False to prevent finish
        self.assertFalse(result)

        # Should emit error observation
        self.mock_controller.event_stream.add_event.assert_called_once()

        # Check observation content
        call_args = self.mock_controller.event_stream.add_event.call_args[0]
        observation = call_args[0]
        self.assertEqual(observation.error_id, "TASK_VALIDATION_FAILED")
        self.assertIn("Missing documentation", observation.content)
        self.assertIn("README.md", observation.content)
        self.assertIn("Add README", observation.content)

    async def test_handle_finish_validation_failed_resumes_agent(self):
        """Test handle_finish resumes agent when validation fails."""
        action = PlaybookFinishAction(outputs={})

        mock_task = MagicMock()
        self.mock_controller._get_initial_task.return_value = mock_task

        mock_validation = MagicMock()
        mock_validation.passed = False
        mock_validation.reason = "Incomplete"
        mock_validation.confidence = 0.9
        mock_validation.missing_items = []
        mock_validation.suggestions = []

        mock_validator = MagicMock()
        mock_validator.validate_completion = AsyncMock(return_value=mock_validation)
        self.mock_controller.task_validator = mock_validator

        self.mock_controller.state.agent_state = AgentState.PAUSED

        with patch("backend.controller.services.task_validation_service.logger"):
            await self.service.handle_finish(action)

        # Should resume agent
        self.mock_controller.set_agent_state_to.assert_called_once_with(
            AgentState.RUNNING
        )

    async def test_handle_finish_validation_failed_already_running(self):
        """Test handle_finish doesn't change state if already running."""
        action = PlaybookFinishAction(outputs={})

        mock_task = MagicMock()
        self.mock_controller._get_initial_task.return_value = mock_task

        mock_validation = MagicMock()
        mock_validation.passed = False
        mock_validation.reason = "Failed"
        mock_validation.confidence = 0.7
        mock_validation.missing_items = []
        mock_validation.suggestions = []

        mock_validator = MagicMock()
        mock_validator.validate_completion = AsyncMock(return_value=mock_validation)
        self.mock_controller.task_validator = mock_validator

        self.mock_controller.state.agent_state = AgentState.RUNNING

        with patch("backend.controller.services.task_validation_service.logger"):
            await self.service.handle_finish(action)

        # Should not change state
        self.mock_controller.set_agent_state_to.assert_not_called()

    async def test_handle_finish_no_initial_task(self):
        """Test handle_finish proceeds when no initial task."""
        action = PlaybookFinishAction(outputs={})

        self.mock_controller._get_initial_task.return_value = None

        mock_validator = MagicMock()
        self.mock_controller.task_validator = mock_validator

        result = await self.service.handle_finish(action)

        # Should return True without validating
        self.assertTrue(result)
        mock_validator.validate_completion.assert_not_called()

    async def test_handle_finish_allows_explicit_test_skip_with_reason(self):
        """Test finish can proceed when tests are explicitly marked not applicable."""
        action = PlaybookFinishAction(
            outputs={
                "tests_not_applicable": True,
                "tests_not_applicable_reason": "No executable test harness exists for this configuration-only change.",
            }
        )
        self.mock_controller.state.history = [MagicMock(action="edit")]
        self.mock_controller.task_validator = None

        result = await self.service.handle_finish(action)

        self.assertTrue(result)

    async def test_handle_finish_blocks_when_completion_validation_enabled_without_validator(self):
        """Test finish is blocked when completion validation is enabled but validator is missing."""
        action = PlaybookFinishAction(outputs={})
        self.mock_controller.task_validator = None
        self.mock_controller.agent = MagicMock()
        self.mock_controller.agent.config = MagicMock()
        self.mock_controller.agent.config.enable_completion_validation = True

        result = await self.service.handle_finish(action)

        self.assertFalse(result)
        self.mock_controller.event_stream.add_event.assert_called_once()

    async def test_build_feedback_complete(self):
        """Test _build_feedback includes all validation details."""
        mock_validation = MagicMock()
        mock_validation.reason = "Incomplete implementation"
        mock_validation.confidence = 0.75
        mock_validation.missing_items = ["feature A", "feature B"]
        mock_validation.suggestions = ["Implement A", "Implement B"]

        feedback = self.service._build_feedback(mock_validation)

        # Should include all components
        self.assertIn("TASK NOT COMPLETE", feedback)
        self.assertIn("Incomplete implementation", feedback)
        self.assertIn("75.0%", feedback)
        self.assertIn("feature A", feedback)
        self.assertIn("feature B", feedback)
        self.assertIn("Implement A", feedback)
        self.assertIn("Implement B", feedback)
        self.assertIn("continue working", feedback)

    async def test_build_feedback_no_missing_items(self):
        """Test _build_feedback without missing items."""
        mock_validation = MagicMock()
        mock_validation.reason = "Quality issue"
        mock_validation.confidence = 0.5
        mock_validation.missing_items = []
        mock_validation.suggestions = ["Improve quality"]

        feedback = self.service._build_feedback(mock_validation)

        # Should not include missing items section
        self.assertNotIn("Missing items:", feedback)
        self.assertIn("Suggestions:", feedback)

    async def test_build_feedback_no_suggestions(self):
        """Test _build_feedback without suggestions."""
        mock_validation = MagicMock()
        mock_validation.reason = "Failed"
        mock_validation.confidence = 0.6
        mock_validation.missing_items = ["item"]
        mock_validation.suggestions = []

        feedback = self.service._build_feedback(mock_validation)

        # Should not include suggestions section
        self.assertNotIn("Suggestions:", feedback)
        self.assertIn("Missing items:", feedback)

    async def test_build_feedback_minimal(self):
        """Test _build_feedback with minimal validation result."""
        mock_validation = MagicMock()
        mock_validation.reason = "Unknown"
        mock_validation.confidence = 0.0
        mock_validation.missing_items = []
        mock_validation.suggestions = []

        feedback = self.service._build_feedback(mock_validation)

        # Should include base information
        self.assertIn("TASK NOT COMPLETE", feedback)
        self.assertIn("Unknown", feedback)
        self.assertIn("0.0%", feedback)


if __name__ == "__main__":
    unittest.main()
