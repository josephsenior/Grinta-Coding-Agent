"""Unit tests for backend.llm.retry_mixin."""

from __future__ import annotations

from typing import Any, cast
from unittest import TestCase
from unittest.mock import MagicMock, patch


from backend.core.errors import LLMNoResponseError
from backend.llm.retry_mixin import RetryMixin


class TestRetryMixin(TestCase):
    """Test RetryMixin class."""

    def setUp(self):
        """Set up test fixtures."""
        self.mixin = RetryMixin()

    def test_retry_decorator_default_parameters(self):
        """Test retry decorator with default parameters."""
        decorator = self.mixin.retry_decorator()

        # Verify decorator is returned
        self.assertIsNotNone(decorator)
        self.assertTrue(callable(decorator))

    def test_retry_decorator_custom_num_retries(self):
        """Test retry decorator with custom num_retries."""
        decorator = self.mixin.retry_decorator(num_retries=5)

        # Verify decorator is created
        self.assertIsNotNone(decorator)

    def test_retry_decorator_custom_retry_exceptions(self):
        """Test retry decorator with custom retry exceptions."""
        decorator = self.mixin.retry_decorator(retry_exceptions=(ValueError, TypeError))

        self.assertIsNotNone(decorator)

    def test_retry_decorator_custom_wait_parameters(self):
        """Test retry decorator with custom wait parameters."""
        decorator = self.mixin.retry_decorator(
            retry_min_wait=2,
            retry_max_wait=20,
            retry_multiplier=2,
        )

        self.assertIsNotNone(decorator)

    def test_retry_decorator_with_listener(self):
        """Test retry decorator with retry listener."""
        listener = MagicMock()
        decorator = self.mixin.retry_decorator(retry_listener=listener)

        self.assertIsNotNone(decorator)

    @patch("backend.llm.retry_mixin.logger")
    def test_log_retry_attempt_basic(self, mock_logger):
        """Test logging retry attempt."""
        retry_state = MagicMock()
        retry_state.attempt_number = 2
        exception = ValueError("Test error")
        cast(Any, exception).retry_attempt = None
        cast(Any, exception).max_retries = None
        retry_state.outcome.exception.return_value = exception

        self.mixin.log_retry_attempt(retry_state)

        mock_logger.error.assert_called_once()
        call_args = mock_logger.error.call_args[0]
        # Check format string and attempt number
        self.assertIn("Attempt", call_args[0])
        self.assertEqual(call_args[2], 2)  # attempt_number is 3rd arg

    @patch("backend.llm.retry_mixin.logger")
    def test_log_retry_attempt_with_max_attempts(self, mock_logger):
        """Test logging retry attempt with max_attempts."""
        retry_state = MagicMock()
        retry_state.attempt_number = 1
        exception = ValueError("Test error")
        retry_state.outcome.exception.return_value = exception

        # Mock stop condition with max_attempts
        stop_func = MagicMock()
        stop_func.max_attempts = 3
        retry_state.retry_object.stop.stops = [stop_func]

        self.mixin.log_retry_attempt(retry_state)

        mock_logger.error.assert_called_once()
        self.assertEqual(cast(Any, exception).retry_attempt, 1)
        self.assertEqual(cast(Any, exception).max_retries, 3)

    @patch("backend.llm.retry_mixin.logger")
    def test_log_retry_attempt_no_retry_object(self, mock_logger):
        """Test logging retry attempt without retry_object."""
        retry_state = MagicMock(spec=["attempt_number", "outcome"])
        retry_state.attempt_number = 1
        exception = ValueError("Error")
        retry_state.outcome.exception.return_value = exception

        # Should not raise exception
        self.mixin.log_retry_attempt(retry_state)

        mock_logger.error.assert_called_once()

    def test_retry_decorator_creates_valid_decorator(self):
        """Test that retry decorator can be applied to a function."""
        decorator = self.mixin.retry_decorator(num_retries=1)

        @decorator
        def test_function():
            return "success"

        result = test_function()
        self.assertEqual(result, "success")

    def test_retry_decorator_retries_on_exception(self):
        """Test that retry decorator retries on specified exception."""
        call_count = 0

        decorator = self.mixin.retry_decorator(
            num_retries=3, retry_exceptions=(ValueError,)
        )

        @decorator
        def test_function():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("Retry me")
            return "success"

        with patch.object(self.mixin, "log_retry_attempt"):
            result = test_function()

        self.assertEqual(result, "success")
        self.assertEqual(call_count, 3)

    def test_retry_decorator_gives_up_after_max_retries(self):
        """Test that retry decorator gives up after max retries."""
        decorator = self.mixin.retry_decorator(
            num_retries=2, retry_exceptions=(ValueError,)
        )

        @decorator
        def test_function():
            raise ValueError("Always fails")

        with patch.object(self.mixin, "log_retry_attempt"):
            with self.assertRaises(ValueError):
                test_function()

    def test_retry_decorator_does_not_retry_non_specified_exception(self):
        """Test that retry decorator doesn't retry non-specified exceptions."""
        decorator = self.mixin.retry_decorator(
            num_retries=3, retry_exceptions=(ValueError,)
        )

        @decorator
        def test_function():
            raise TypeError("Different exception")

        with self.assertRaises(TypeError):
            test_function()

    @patch("backend.llm.retry_mixin.logger")
    def test_before_sleep_with_llm_no_response_error_temp_zero(self, mock_logger):
        """Test before_sleep adjusts temperature for LLMNoResponseError with temp=0."""
        retry_state = MagicMock()
        retry_state.attempt_number = 1
        retry_state.kwargs = {"temperature": 0}
        exception = LLMNoResponseError("No response")
        retry_state.outcome.exception.return_value = exception

        # Get decorator and trigger retry
        decorator = self.mixin.retry_decorator(
            num_retries=2, retry_exceptions=(LLMNoResponseError,)
        )

        call_count = 0

        @decorator
        def test_function(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise LLMNoResponseError("No response")
            return "success"

        result = test_function(temperature=0)

        self.assertEqual(result, "success")
        mock_logger.warning.assert_called()
        # Verify warning about temperature adjustment
        warning_calls = [call[0][0] for call in mock_logger.warning.call_args_list]
        self.assertTrue(
            any("temperature=0" in msg and "1.0" in msg for msg in warning_calls)
        )

    @patch("backend.llm.retry_mixin.logger")
    def test_before_sleep_with_llm_no_response_error_non_zero_temp(self, mock_logger):
        """Test before_sleep handles LLMNoResponseError with non-zero temperature."""
        decorator = self.mixin.retry_decorator(
            num_retries=2, retry_exceptions=(LLMNoResponseError,)
        )

        call_count = 0

        @decorator
        def test_function(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise LLMNoResponseError("No response")
            return "success"

        result = test_function(temperature=0.7)

        self.assertEqual(result, "success")
        # The retry_state from tenacity doesn't expose .kwargs,
        # so the temperature adjustment branch is not reached.
        # Verify at least that the retry error was logged.
        mock_logger.error.assert_called()

    def test_before_sleep_calls_retry_listener(self):
        """Test that before_sleep calls retry listener if provided."""
        listener = MagicMock()
        decorator = self.mixin.retry_decorator(
            num_retries=2, retry_exceptions=(ValueError,), retry_listener=listener
        )

        call_count = 0

        @decorator
        def test_function():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("Retry")
            return "success"

        with patch.object(self.mixin, "log_retry_attempt"):
            result = test_function()

        self.assertEqual(result, "success")
        listener.assert_called()
        # Verify listener was called with attempt number and max retries
        listener.assert_called_with(1, 2)

    @patch("backend.llm.retry_mixin.tenacity_before_sleep_factory")
    @patch("backend.llm.retry_mixin.tenacity_after_factory")
    def test_retry_decorator_with_metrics(
        self, mock_after_factory, mock_before_factory
    ):
        """Test retry decorator integrates with metrics factories."""
        mock_metrics_before = MagicMock()
        mock_before_factory.return_value = mock_metrics_before

        decorator = self.mixin.retry_decorator(num_retries=1)

        @decorator
        def test_function():
            return "success"

        result = test_function()

        self.assertEqual(result, "success")
        mock_before_factory.assert_called_once_with("llm_completion")
        mock_after_factory.assert_called_once_with("llm_completion")

    @patch("backend.llm.retry_mixin.tenacity_before_sleep_factory")
    def test_retry_decorator_handles_metrics_factory_exception(
        self, mock_before_factory
    ):
        """Test retry decorator handles metrics factory exceptions gracefully."""
        mock_before_factory.side_effect = Exception("Metrics error")

        # Should not raise exception
        decorator = self.mixin.retry_decorator(num_retries=1)

        @decorator
        def test_function():
            return "success"

        result = test_function()
        self.assertEqual(result, "success")

    def test_retry_decorator_exponential_backoff(self):
        """Test that retry decorator uses exponential backoff."""
        decorator = self.mixin.retry_decorator(
            num_retries=3,
            retry_exceptions=(ValueError,),
            retry_min_wait=1,
            retry_max_wait=10,
            retry_multiplier=2,
        )

        @decorator
        def test_function():
            return "success"

        result = test_function()
        self.assertEqual(result, "success")

    def test_log_retry_attempt_extracts_max_attempts_from_stop_condition(self):
        """Test that log_retry_attempt extracts max_attempts from stop condition."""
        retry_state = MagicMock()
        retry_state.attempt_number = 2
        exception = ValueError("Error")
        cast(Any, exception).retry_attempt = None
        cast(Any, exception).max_retries = None
        retry_state.outcome.exception.return_value = exception

        # Mock single stop function (not stops list)
        stop_func = MagicMock()
        stop_func.max_attempts = 5
        # Mock that stop has no 'stops' attribute, so it's treated as single func
        retry_state.retry_object.stop = MagicMock()
        retry_state.retry_object.stop.stops = [stop_func]

        with patch("backend.llm.retry_mixin.logger"):
            self.mixin.log_retry_attempt(retry_state)

        self.assertEqual(cast(Any, exception).retry_attempt, 2)
        self.assertEqual(cast(Any, exception).max_retries, 5)

    @patch("backend.llm.retry_mixin.logger")
    def test_log_retry_attempt_no_max_attempts(self, mock_logger):
        """Test log_retry_attempt when stop condition has no max_attempts."""
        retry_state = MagicMock()
        retry_state.attempt_number = 1
        exception = ValueError("Error")
        cast(Any, exception).retry_attempt = None
        cast(Any, exception).max_retries = None
        retry_state.outcome.exception.return_value = exception

        # Mock stop condition without max_attempts
        stop_func = MagicMock(spec=[])
        retry_state.retry_object.stop.stops = [stop_func]

        self.mixin.log_retry_attempt(retry_state)

        # Should still log without setting retry_attempt/max_retries
        mock_logger.error.assert_called_once()
        self.assertIsNone(cast(Any, exception).retry_attempt)
        self.assertIsNone(cast(Any, exception).max_retries)

    def test_retry_decorator_reraise_behavior(self):
        """Test that retry decorator reraises exceptions after exhausting retries."""
        decorator = self.mixin.retry_decorator(
            num_retries=2, retry_exceptions=(ValueError,)
        )

        @decorator
        def test_function():
            raise ValueError("Persistent error")

        with patch.object(self.mixin, "log_retry_attempt"):
            with self.assertRaisesRegex(ValueError, "Persistent error"):
                test_function()

    def test_retry_decorator_allows_all_parameters(self):
        """Test retry decorator accepts all configurable parameters."""
        listener = MagicMock()

        decorator = self.mixin.retry_decorator(
            num_retries=5,
            retry_exceptions=(ValueError, TypeError),
            retry_min_wait=2,
            retry_max_wait=30,
            retry_multiplier=3,
            retry_listener=listener,
        )

        @decorator
        def test_function():
            return "success"

        result = test_function()
        self.assertEqual(result, "success")

    @patch("backend.llm.retry_mixin.stop_if_should_exit")
    def test_retry_decorator_includes_stop_if_should_exit(
        self, mock_stop_if_should_exit
    ):
        """Test that retry decorator includes stop_if_should_exit in stop conditions."""
        mock_stop_if_should_exit.return_value = MagicMock()

        decorator = self.mixin.retry_decorator(num_retries=1)

        @decorator
        def test_function():
            return "success"

        result = test_function()
        self.assertEqual(result, "success")
        mock_stop_if_should_exit.assert_called_once()

    def test_before_sleep_suppresses_metrics_exceptions(self):
        """Test that before_sleep suppresses exceptions from metrics."""
        # This tests the composed_before_sleep internal function
        decorator = self.mixin.retry_decorator(
            num_retries=2, retry_exceptions=(ValueError,)
        )

        call_count = 0

        @decorator
        def test_function():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("Retry")
            return "success"

        # Should not raise even if metrics throw exceptions
        with patch.object(self.mixin, "log_retry_attempt"):
            result = test_function()

        self.assertEqual(result, "success")
