"""Tests for RetryService."""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.orchestration.services.retry_service import RetryService


class TestRetryService(unittest.IsolatedAsyncioTestCase):
    """Test RetryService retry orchestration logic."""

    def setUp(self):
        """Create mock context and controller for testing."""
        self.mock_context = MagicMock()
        self.mock_controller = MagicMock()
        self.mock_controller.id = 'test-controller-123'
        self.mock_controller._closed = False
        self.mock_controller._pending_action = None
        self.mock_controller.state = MagicMock()
        self.mock_controller.state.set_last_error = MagicMock()
        self.mock_controller.event_stream = MagicMock()
        self.mock_controller.circuit_breaker_service = MagicMock()
        self.mock_controller.circuit_breaker_service.record_success = MagicMock()
        self.mock_controller.circuit_breaker_service.circuit_breaker = MagicMock()
        self.mock_controller.circuit_breaker_service.circuit_breaker.consecutive_errors = 1
        self.mock_controller.set_agent_state_to = AsyncMock()
        self.mock_controller.step = MagicMock()
        self.mock_controller.log = MagicMock()
        self.mock_context.get_controller.return_value = self.mock_controller

        self.service = RetryService(self.mock_context)

    def test_controller_accessor(self):
        """Test controller accessor returns controller from context."""
        result = self.service.controller

        self.assertEqual(result, self.mock_controller)

    @patch('backend.orchestration.services.retry_service.get_retry_queue')
    def test_initialize_no_queue(self, mock_get_queue):
        """Test initialize does nothing when no retry queue."""
        mock_get_queue.return_value = None

        self.service.initialize()

        # Should not start worker
        self.assertIsNone(self.service._retry_worker_task)

    @patch('backend.orchestration.services.retry_service.get_retry_queue')
    @patch('backend.orchestration.services.retry_service.logger')
    async def test_initialize_no_event_loop(self, mock_logger, mock_get_queue):
        """Test initialize warns when no event loop available."""
        mock_queue = MagicMock()
        mock_get_queue.return_value = mock_queue

        # Create service without running loop
        service_no_loop = RetryService(self.mock_context)

        # Call initialize outside async context
        with patch(
            'backend.orchestration.services.retry_service.asyncio.get_running_loop',
            side_effect=RuntimeError('No loop'),
        ):
            service_no_loop.initialize()

        # Should log warning
        mock_logger.warning.assert_called_once()
        self.assertIsNone(service_no_loop._retry_worker_task)

    @patch('backend.orchestration.services.retry_service.get_retry_queue')
    async def test_initialize_with_queue(self, mock_get_queue):
        """Test initialize starts retry worker when queue available."""
        mock_queue = MagicMock()
        mock_queue.poll_interval = 1.0
        mock_get_queue.return_value = mock_queue

        self.service.initialize()

        # Should start worker task
        self.assertIsNotNone(self.service._retry_worker_task)
        self.assertIsNotNone(self.service._task_loop)

        # Cleanup
        task = self.service._retry_worker_task
        assert task is not None
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    def test_reset_retry_metrics(self):
        """Test reset_retry_metrics clears retry state."""
        self.service._retry_count = 5
        self.service._retry_pending = True

        self.service.reset_retry_metrics()

        self.assertEqual(self.service._retry_count, 0)
        self.assertFalse(self.service._retry_pending)

    def test_increment_retry_count(self):
        """Test increment_retry_count increases counter."""
        self.service._retry_count = 2

        result = self.service.increment_retry_count()

        self.assertEqual(result, 3)
        self.assertEqual(self.service.retry_count, 3)

    def test_retry_count_property(self):
        """Test retry_count property returns current count."""
        self.service._retry_count = 7

        self.assertEqual(self.service.retry_count, 7)

    def test_retry_pending_property(self):
        """Test retry_pending property returns pending state."""
        self.service._retry_pending = True

        self.assertTrue(self.service.retry_pending)

    @patch('backend.orchestration.services.retry_service.get_retry_queue')
    async def test_schedule_retry_no_queue(self, mock_get_queue):
        """Test schedule_retry_after_failure returns False when no queue."""
        from backend.inference.exceptions import APIConnectionError

        mock_get_queue.return_value = None
        exc = APIConnectionError('Connection failed')

        result = await self.service.schedule_retry_after_failure(exc)

        self.assertFalse(result)

    @patch('backend.orchestration.services.retry_service.get_retry_queue')
    async def test_schedule_retry_non_retryable_exception(self, mock_get_queue):
        """Test schedule_retry_after_failure returns False for non-retryable errors."""
        mock_queue = MagicMock()
        mock_get_queue.return_value = mock_queue

        exc = ValueError('Not retryable')

        result = await self.service.schedule_retry_after_failure(exc)

        self.assertFalse(result)

    @patch('backend.orchestration.services.retry_service.get_retry_queue')
    @patch('backend.orchestration.services.retry_service.logger')
    async def test_schedule_retry_already_pending(self, mock_logger, mock_get_queue):
        """Test schedule_retry_after_failure when retry already pending."""
        from backend.inference.exceptions import Timeout

        mock_queue = MagicMock()
        mock_get_queue.return_value = mock_queue

        self.service._retry_pending = True
        exc = Timeout('Timeout')

        result = await self.service.schedule_retry_after_failure(exc)

        # Should return True but not schedule
        self.assertTrue(result)
        mock_logger.debug.assert_called()

    @patch('backend.orchestration.services.retry_service.get_retry_queue')
    async def test_schedule_retry_api_connection_error(self, mock_get_queue):
        """Test schedule_retry_after_failure schedules for APIConnectionError."""
        from backend.inference.exceptions import APIConnectionError
        from backend.ledger.observation import StatusObservation

        mock_task = MagicMock()
        mock_task.id = 'retry-123'
        mock_task.max_attempts = 3
        mock_task.attempts = 0

        mock_queue = MagicMock()
        mock_queue.base_delay = 5.0
        mock_queue.max_delay = 300.0
        mock_queue.schedule = AsyncMock(return_value=mock_task)
        mock_get_queue.return_value = mock_queue

        exc = APIConnectionError('Connection failed')

        result = await self.service.schedule_retry_after_failure(exc)

        # Should schedule retry
        self.assertTrue(result)
        self.assertTrue(self.service._retry_pending)
        mock_queue.schedule.assert_called_once()

        # Should emit retry telemetry observation
        self.mock_controller.event_stream.add_event.assert_called_once()
        event = self.mock_controller.event_stream.add_event.call_args[0][0]
        self.assertIsInstance(event, StatusObservation)
        self.assertEqual(event.status_type, 'retry_pending')
        self.assertEqual(event.extras['attempt'], 1)
        self.assertEqual(event.extras['max_attempts'], 3)
        self.assertIn('autonomous recovery', event.content.lower())

    @patch('backend.orchestration.services.retry_service.get_retry_queue')
    async def test_schedule_retry_rate_limit_error_longer_delay(self, mock_get_queue):
        """Test schedule_retry_after_failure uses longer delay for rate limits."""
        from backend.inference.exceptions import RateLimitError

        mock_task = MagicMock()
        mock_task.id = 'retry-456'
        mock_task.max_attempts = 5

        mock_queue = MagicMock()
        mock_queue.base_delay = 10.0
        mock_queue.max_delay = 300.0
        mock_queue.schedule = AsyncMock(return_value=mock_task)
        mock_get_queue.return_value = mock_queue

        exc = RateLimitError('Rate limited')

        await self.service.schedule_retry_after_failure(exc)

        # Should schedule with increased delay
        call_kwargs = mock_queue.schedule.call_args[1]
        self.assertGreaterEqual(call_kwargs['initial_delay'], 10.0)

    @patch('backend.orchestration.services.retry_service.get_retry_queue')
    async def test_schedule_retry_with_circuit_breaker(self, mock_get_queue):
        """Test schedule_retry_after_failure adjusts delay based on circuit breaker."""
        from backend.inference.exceptions import Timeout

        mock_task = MagicMock()
        mock_task.id = 'retry-789'
        mock_task.max_attempts = 3

        mock_queue = MagicMock()
        mock_queue.base_delay = 5.0
        mock_queue.max_delay = 300.0
        mock_queue.schedule = AsyncMock(return_value=mock_task)
        mock_get_queue.return_value = mock_queue

        # Mock circuit breaker with consecutive errors
        mock_circuit_breaker = MagicMock()
        mock_circuit_breaker.consecutive_errors = 3
        self.mock_controller.circuit_breaker_service.circuit_breaker = (
            mock_circuit_breaker
        )

        exc = Timeout('Timeout')

        await self.service.schedule_retry_after_failure(exc)

        # Should adjust delay based on consecutive errors
        call_kwargs = mock_queue.schedule.call_args[1]
        self.assertGreater(call_kwargs['initial_delay'], 5.0)

    async def test_shutdown_no_worker(self):
        """Test shutdown does nothing when no worker task."""
        await self.service.shutdown()

        # Should not raise exception
        self.assertIsNone(self.service._retry_worker_task)

    async def test_shutdown_cancels_worker(self):
        """Test shutdown cancels retry worker task."""
        # Create a mock task
        mock_task = MagicMock()
        mock_task.cancel = MagicMock()
        mock_task.done = MagicMock(return_value=False)

        # Create a real coroutine that can be cancelled
        async def dummy_worker():
            try:
                await asyncio.sleep(100)
            except asyncio.CancelledError:
                raise

        task = asyncio.create_task(dummy_worker())
        self.service._retry_worker_task = task
        self.service._task_loop = asyncio.get_running_loop()

        await self.service.shutdown()

        # Should clean up task
        self.assertIsNone(self.service._retry_worker_task)
        self.assertIsNone(self.service._task_loop)

    @patch('backend.orchestration.services.retry_service.get_retry_queue')
    async def test_fetch_ready_tasks_returns_empty(self, mock_get_queue):
        """Test _fetch_ready_tasks returns empty list when no tasks."""
        mock_queue = MagicMock()
        mock_queue.fetch_ready = AsyncMock(return_value=[])
        self.service._retry_queue = mock_queue

        result = await self.service._fetch_ready_tasks(self.mock_controller, 0.1)

        self.assertEqual(result, [])

    @patch('backend.orchestration.services.retry_service.get_retry_queue')
    async def test_fetch_ready_tasks_returns_tasks(self, mock_get_queue):
        """Test _fetch_ready_tasks returns available tasks."""
        mock_task = MagicMock()
        mock_task.id = 'task-123'

        mock_queue = MagicMock()
        mock_queue.fetch_ready = AsyncMock(return_value=[mock_task])
        self.service._retry_queue = mock_queue

        result = await self.service._fetch_ready_tasks(self.mock_controller, 0.1)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].id, 'task-123')

    def test_is_retry_backend_failure_connection_error(self):
        """Test _is_retry_backend_failure identifies ConnectionError."""
        exc = ConnectionError('Connection lost')

        result = self.service._is_retry_backend_failure(exc)

        self.assertTrue(result)

    def test_is_retry_backend_failure_os_error(self):
        """Test _is_retry_backend_failure identifies OSError."""
        exc = OSError('OS error')

        result = self.service._is_retry_backend_failure(exc)

        self.assertTrue(result)

    def test_is_retry_backend_failure_other_error(self):
        """Test _is_retry_backend_failure returns False for other errors."""
        exc = ValueError('Not a backend error')

        result = self.service._is_retry_backend_failure(exc)

        self.assertFalse(result)

    async def test_resume_agent_after_retry(self):
        """Test _resume_agent_after_retry resumes agent."""
        from backend.ledger.observation import StatusObservation
        from backend.orchestration.state.state import AgentState

        mock_task = MagicMock()
        mock_task.reason = 'APIConnectionError'
        mock_task.attempts = 2
        mock_task.max_attempts = 5
        mock_task.metadata = {'retry_reason': 'APIConnectionError'}

        self.mock_controller.state.agent_state = AgentState.ERROR
        # No budget/iteration limits configured in this scenario
        self.mock_controller.state.budget_flag = None
        self.mock_controller.state.iteration_flag = None

        await self.service._resume_agent_after_retry(mock_task)

        # Should record success
        self.mock_controller.circuit_breaker_service.record_success.assert_called_once()

        # Should emit retry telemetry observation
        self.mock_controller.event_stream.add_event.assert_called_once()
        event = self.mock_controller.event_stream.add_event.call_args[0][0]
        self.assertIsInstance(event, StatusObservation)
        self.assertEqual(event.status_type, 'retry_resuming')
        self.assertEqual(event.extras['attempt'], 2)
        self.assertEqual(event.extras['max_attempts'], 5)
        self.assertIn('2/5', event.content)

        # Should set state to running
        self.mock_controller.set_agent_state_to.assert_called_once()

        # Should reset retry state
        self.assertFalse(self.service._retry_pending)
        self.assertEqual(self.service._retry_count, 0)

        # Should trigger step
        self.mock_controller.step.assert_called_once()

    async def test_resume_agent_after_retry_already_running(self):
        """Test _resume_agent_after_retry when already running."""
        from backend.orchestration.state.state import AgentState

        mock_task = MagicMock()
        mock_task.reason = 'Timeout'
        mock_task.attempts = 1
        mock_task.max_attempts = 3
        mock_task.metadata = {'retry_reason': 'Timeout'}

        self.mock_controller.state.agent_state = AgentState.RUNNING
        # No budget/iteration limits configured in this scenario
        self.mock_controller.state.budget_flag = None
        self.mock_controller.state.iteration_flag = None

        await self.service._resume_agent_after_retry(mock_task)

        # Should not change state
        self.mock_controller.set_agent_state_to.assert_not_called()

    async def test_resume_agent_after_retry_aborts_when_budget_limit_reached(self):
        """Test _resume_agent_after_retry returns control to the user on limit exhaustion."""
        budget_flag = MagicMock()
        budget_flag.reached_limit.return_value = True

        self.mock_controller.state.budget_flag = budget_flag
        self.mock_controller.state.iteration_flag = None
        self.service._retry_pending = True
        self.service._retry_count = 3

        mock_task = MagicMock()
        mock_task.id = 'retry-123'
        mock_task.reason = 'Timeout'
        mock_task.attempts = 1
        mock_task.max_attempts = 3
        mock_task.metadata = {'retry_reason': 'Timeout'}

        with patch.object(
            self.service, '_transition_to_awaiting_user', new_callable=AsyncMock
        ) as mock_transition:
            await self.service._resume_agent_after_retry(mock_task)

        self.mock_controller.circuit_breaker_service.record_success.assert_not_called()
        self.mock_controller.step.assert_not_called()
        self.mock_controller.set_agent_state_to.assert_not_called()
        self.assertFalse(self.service._retry_pending)
        self.assertEqual(self.service._retry_count, 0)
        mock_transition.assert_called_once_with()

    async def test_stop_if_idle_delegates_to_shutdown(self):
        """Test stop_if_idle delegates to shutdown."""
        with patch.object(
            self.service, 'shutdown', new_callable=AsyncMock
        ) as mock_shutdown:
            await self.service.stop_if_idle()

            mock_shutdown.assert_called_once()


if __name__ == '__main__':
    unittest.main()
