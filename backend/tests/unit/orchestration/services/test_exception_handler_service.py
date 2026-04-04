"""Tests for ExceptionHandlerService."""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.core.errors import LLMContextWindowExceedError, ModelProviderError
from backend.inference.exceptions import (
    APIConnectionError,
    APIError,
    AuthenticationError,
    BadRequestError,
    ContentPolicyViolationError,
    ContextWindowExceededError,
    InternalServerError,
    NotFoundError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
)
from backend.orchestration.services.exception_handler_service import (
    ExceptionHandlerService,
)


class TestExceptionHandlerService(unittest.IsolatedAsyncioTestCase):
    """Test ExceptionHandlerService exception handling logic."""

    def setUp(self):
        """Create mock controller for testing."""
        self.mock_controller = MagicMock()
        self.mock_controller.id = 'test-controller'
        self.mock_controller.log = MagicMock()
        self.mock_controller.recovery_service = MagicMock()
        self.mock_controller.recovery_service.react_to_exception = AsyncMock()

        self.service = ExceptionHandlerService(self.mock_controller)

    @patch('backend.orchestration.services.exception_handler_service.logger')
    async def test_handle_step_exception_timeout(self, mock_logger):
        """Test handle_step_exception forwards Timeout exception."""
        exc = Timeout('Request timeout')

        await self.service.handle_step_exception(exc)

        # Should forward exception to recovery
        self.mock_controller.recovery_service.react_to_exception.assert_called_once_with(
            exc
        )

        # Should log error
        self.mock_controller.log.assert_called_once()

    @patch('backend.orchestration.services.exception_handler_service.logger')
    async def test_handle_step_exception_api_error(self, mock_logger):
        """Test handle_step_exception forwards APIError exception."""
        exc = APIError('API error')

        await self.service.handle_step_exception(exc)

        # Should forward exception
        self.mock_controller.recovery_service.react_to_exception.assert_called_once_with(
            exc
        )

    @patch('backend.orchestration.services.exception_handler_service.logger')
    async def test_handle_step_exception_api_connection_error(self, mock_logger):
        """Test handle_step_exception forwards APIConnectionError."""
        exc = APIConnectionError('Connection failed')

        await self.service.handle_step_exception(exc)

        # Should forward exception
        self.mock_controller.recovery_service.react_to_exception.assert_called_once_with(
            exc
        )

    @patch('backend.orchestration.services.exception_handler_service.logger')
    async def test_handle_step_exception_bad_request_error(self, mock_logger):
        """Test handle_step_exception forwards BadRequestError."""
        exc = BadRequestError('Bad request')

        await self.service.handle_step_exception(exc)

        # Should forward exception
        self.mock_controller.recovery_service.react_to_exception.assert_called_once_with(
            exc
        )

    @patch('backend.orchestration.services.exception_handler_service.logger')
    async def test_handle_step_exception_not_found_error(self, mock_logger):
        """Test handle_step_exception forwards NotFoundError."""
        exc = NotFoundError('Not found')

        await self.service.handle_step_exception(exc)

        # Should forward exception
        self.mock_controller.recovery_service.react_to_exception.assert_called_once_with(
            exc
        )

    @patch('backend.orchestration.services.exception_handler_service.logger')
    async def test_handle_step_exception_internal_server_error(self, mock_logger):
        """Test handle_step_exception forwards InternalServerError."""
        exc = InternalServerError('Internal error')

        await self.service.handle_step_exception(exc)

        # Should forward exception
        self.mock_controller.recovery_service.react_to_exception.assert_called_once_with(
            exc
        )

    @patch('backend.orchestration.services.exception_handler_service.logger')
    async def test_handle_step_exception_authentication_error(self, mock_logger):
        """Test handle_step_exception forwards AuthenticationError."""
        exc = AuthenticationError('Auth failed')

        await self.service.handle_step_exception(exc)

        # Should forward exception
        self.mock_controller.recovery_service.react_to_exception.assert_called_once_with(
            exc
        )

    @patch('backend.orchestration.services.exception_handler_service.logger')
    async def test_handle_step_exception_rate_limit_error(self, mock_logger):
        """Test handle_step_exception forwards RateLimitError."""
        exc = RateLimitError('Rate limited')

        await self.service.handle_step_exception(exc)

        # Should forward exception
        self.mock_controller.recovery_service.react_to_exception.assert_called_once_with(
            exc
        )

    @patch('backend.orchestration.services.exception_handler_service.logger')
    async def test_handle_step_exception_service_unavailable_error(self, mock_logger):
        """Test handle_step_exception forwards ServiceUnavailableError."""
        exc = ServiceUnavailableError('Service unavailable')

        await self.service.handle_step_exception(exc)

        # Should forward exception
        self.mock_controller.recovery_service.react_to_exception.assert_called_once_with(
            exc
        )

    @patch('backend.orchestration.services.exception_handler_service.logger')
    async def test_handle_step_exception_content_policy_violation(self, mock_logger):
        """Test handle_step_exception forwards ContentPolicyViolationError."""
        exc = ContentPolicyViolationError('Policy violation')

        await self.service.handle_step_exception(exc)

        # Should forward exception
        self.mock_controller.recovery_service.react_to_exception.assert_called_once_with(
            exc
        )

    @patch('backend.orchestration.services.exception_handler_service.logger')
    async def test_handle_step_exception_context_window_exceeded(self, mock_logger):
        """Test handle_step_exception forwards ContextWindowExceededError."""
        exc = ContextWindowExceededError('Context too large')

        await self.service.handle_step_exception(exc)

        # Should forward exception
        self.mock_controller.recovery_service.react_to_exception.assert_called_once_with(
            exc
        )

    @patch('backend.orchestration.services.exception_handler_service.logger')
    async def test_handle_step_exception_llm_context_window_exceed(self, mock_logger):
        """Test handle_step_exception forwards LLMContextWindowExceedError."""
        exc = LLMContextWindowExceedError('LLM context exceeded')

        await self.service.handle_step_exception(exc)

        # Should forward exception
        self.mock_controller.recovery_service.react_to_exception.assert_called_once_with(
            exc
        )

    @patch('backend.orchestration.services.exception_handler_service.logger')
    async def test_handle_step_exception_model_provider_error(self, mock_logger):
        """Test handle_step_exception forwards ModelProviderError."""
        exc = ModelProviderError('LLM returned no response')

        await self.service.handle_step_exception(exc)

        self.mock_controller.recovery_service.react_to_exception.assert_called_once_with(
            exc
        )

    @patch('backend.orchestration.services.exception_handler_service.logger')
    async def test_handle_step_exception_generic_error(self, mock_logger):
        """Test handle_step_exception wraps generic exceptions."""
        exc = ValueError('Some error')

        await self.service.handle_step_exception(exc)

        # Should wrap in RuntimeError
        call_args = self.mock_controller.recovery_service.react_to_exception.call_args[
            0
        ]
        reported_exc = call_args[0]
        self.assertIsInstance(reported_exc, RuntimeError)
        self.assertIn('unexpected error', str(reported_exc))
        self.assertIn('ValueError', str(reported_exc))

    @patch('backend.orchestration.services.exception_handler_service.logger')
    async def test_handle_step_exception_logs_traceback(self, mock_logger):
        """Test handle_step_exception logs exception traceback."""
        exc = RuntimeError('Test error')

        await self.service.handle_step_exception(exc)

        # Should log error traceback
        mock_logger.error.assert_called()

        # Verify right message logged
        error_calls = [
            c for c in mock_logger.error.mock_calls if 'traceback' in c[1][0]
        ]
        self.assertTrue(len(error_calls) > 0)
        call_args = error_calls[0][1]
        self.assertIn('test-controller', call_args[1])

    @patch('backend.orchestration.services.exception_handler_service.logger')
    async def test_handle_step_exception_logs_error_type(self, mock_logger):
        """Test handle_step_exception logs exception type."""
        exc = APIError('Test error')

        await self.service.handle_step_exception(exc)

        # Should log with exception type in extra
        call_kwargs = self.mock_controller.log.call_args[1]
        self.assertEqual(call_kwargs['extra']['exception_type'], 'APIError')

    @patch('backend.orchestration.services.exception_handler_service.logger')
    async def test_handle_step_exception_zero_division_error(self, mock_logger):
        """Test handle_step_exception wraps ZeroDivisionError."""
        exc = ZeroDivisionError('Division by zero')

        await self.service.handle_step_exception(exc)

        # Should wrap in RuntimeError
        call_args = self.mock_controller.recovery_service.react_to_exception.call_args[
            0
        ]
        reported_exc = call_args[0]
        self.assertIsInstance(reported_exc, RuntimeError)
        self.assertIn('ZeroDivisionError', str(reported_exc))

    @patch('backend.orchestration.services.exception_handler_service.logger')
    async def test_handle_step_exception_attribute_error(self, mock_logger):
        """Test handle_step_exception wraps AttributeError."""
        exc = AttributeError('Missing attribute')

        await self.service.handle_step_exception(exc)

        # Should wrap in RuntimeError
        call_args = self.mock_controller.recovery_service.react_to_exception.call_args[
            0
        ]
        reported_exc = call_args[0]
        self.assertIsInstance(reported_exc, RuntimeError)

    @patch('backend.orchestration.services.exception_handler_service.logger')
    async def test_handle_step_exception_key_error(self, mock_logger):
        """Test handle_step_exception wraps KeyError."""
        exc = KeyError('missing_key')

        await self.service.handle_step_exception(exc)

        # Should wrap in RuntimeError
        call_args = self.mock_controller.recovery_service.react_to_exception.call_args[
            0
        ]
        reported_exc = call_args[0]
        self.assertIsInstance(reported_exc, RuntimeError)


if __name__ == '__main__':
    unittest.main()
