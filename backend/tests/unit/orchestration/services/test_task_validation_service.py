"""Tests for TaskValidationService.

The service exposes a single ``validate_completion_quality`` method that
runs the optional LLM-judge (``task_validator``) and emits a warning
observation on failure.  It never blocks the transition to
``AgentState.FINISHED``.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from backend.ledger.action import MessageAction
from backend.orchestration.services.task_validation_service import TaskValidationService


class TestValidateCompletionQuality(unittest.IsolatedAsyncioTestCase):
    """Test the optional LLM-judge quality gate."""

    def setUp(self):
        self.mock_context = MagicMock()
        self.mock_controller = MagicMock()
        self.mock_controller.state = MagicMock()
        self.mock_controller.event_stream = MagicMock()
        self.mock_controller.event_stream.add_event = MagicMock()
        self.mock_controller._get_initial_task = MagicMock(
            return_value=SimpleNamespace(description='task')
        )
        self.mock_controller.task_validator = None
        self.mock_context.get_controller.return_value = self.mock_controller
        self.service = TaskValidationService(self.mock_context)

    async def test_no_validator_returns_silently(self):
        action = MessageAction(content='Done.', final_response=True)
        await self.service.validate_completion_quality(action)
        self.mock_controller.event_stream.add_event.assert_not_called()

    async def test_validator_disabled_returns_silently(self):
        action = MessageAction(content='Done.', final_response=True)
        self.mock_controller.task_validator = MagicMock()
        self.mock_controller.agent.config = SimpleNamespace(
            enable_completion_validation=False
        )

        await self.service.validate_completion_quality(action)
        self.mock_controller.event_stream.add_event.assert_not_called()
        self.mock_controller.task_validator.validate_completion.assert_not_called()

    async def test_validator_passes_emits_no_observation(self):
        action = MessageAction(content='Done.', final_response=True)
        self.mock_controller.task_validator = MagicMock()
        self.mock_controller.task_validator.validate_completion = AsyncMock(
            return_value=SimpleNamespace(passed=True, reason='OK', confidence=1.0)
        )
        self.mock_controller.agent.config = SimpleNamespace(
            enable_completion_validation=True
        )

        await self.service.validate_completion_quality(action)
        self.mock_controller.event_stream.add_event.assert_not_called()

    async def test_validator_fails_emits_warning_observation(self):
        action = MessageAction(content='Done.', final_response=True)
        self.mock_controller.task_validator = MagicMock()
        self.mock_controller.task_validator.validate_completion = AsyncMock(
            return_value=SimpleNamespace(
                passed=False,
                reason='Looks rushed',
                confidence=0.8,
                missing_items=['README'],
                suggestions=['Add docs'],
            )
        )
        self.mock_controller.agent.config = SimpleNamespace(
            enable_completion_validation=True
        )

        await self.service.validate_completion_quality(action)

        self.mock_controller.event_stream.add_event.assert_called_once()
        warning = self.mock_controller.event_stream.add_event.call_args[0][0]
        self.assertEqual(warning.error_id, 'COMPLETION_VALIDATOR_NOTE')
        self.assertIn('Looks rushed', warning.content)
        self.assertIn('README', warning.content)
        self.assertIn('Add docs', warning.content)

    async def test_validator_raises_is_swallowed(self):
        action = MessageAction(content='Done.', final_response=True)
        self.mock_controller.task_validator = MagicMock()
        self.mock_controller.task_validator.validate_completion = AsyncMock(
            side_effect=RuntimeError('boom')
        )
        self.mock_controller.agent.config = SimpleNamespace(
            enable_completion_validation=True
        )

        with patch(
            'backend.orchestration.services.task_validation_service.logger'
        ) as mock_logger:
            await self.service.validate_completion_quality(action)
        mock_logger.warning.assert_called()
        self.mock_controller.event_stream.add_event.assert_not_called()


if __name__ == '__main__':
    unittest.main()
