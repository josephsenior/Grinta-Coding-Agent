from typing import Any, cast
"""Tests for RecoveryService."""

import unittest
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

from backend.controller.error_recovery import ErrorType
from backend.controller.services.recovery_service import RecoveryService
from backend.core.enums import RuntimeStatus


class TestRecoveryService(unittest.IsolatedAsyncioTestCase):
    """Test RecoveryService error recovery logic."""

    def setUp(self):
        """Create mock context and service for testing."""
        self.mock_controller = MagicMock()
        self.mock_controller.log = MagicMock()
        self.mock_controller.state = MagicMock()
        self.mock_controller.state.last_error = ""
        self.mock_controller.state.set_last_error = MagicMock()
        self.mock_controller.event_stream = MagicMock()
        self.mock_controller.status_callback = None
        self.mock_controller.circuit_breaker_service = MagicMock()
        self.mock_controller.set_agent_state_to = AsyncMock()
        self.mock_controller.log_task_audit = AsyncMock()

        self.mock_context = MagicMock()
        self.mock_context.get_controller.return_value = self.mock_controller
        self.mock_context.emit_event = MagicMock()

        self.mock_retry_service = MagicMock()
        self.mock_retry_service.retry_count = 0
        self.mock_retry_service.increment_retry_count = MagicMock()
        self.mock_retry_service.schedule_retry_after_failure = AsyncMock(
            return_value=False
        )

        self.service = RecoveryService(
            self.mock_context, self.mock_retry_service, max_retries=3
        )

    # ── react_to_exception ──────────────────────────────────────────

    async def test_react_to_exception_calls_try_recovery(self):
        """Test react_to_exception classifies error and tries recovery."""
        exc = RuntimeError("Test error")

        with patch.object(
            self.service, "_try_error_recovery", new_callable=AsyncMock
        ) as mock_try:
            mock_try.return_value = True
            await self.service.react_to_exception(exc)

        mock_try.assert_called_once()
        self.mock_controller.state.set_last_error.assert_called_once()

    async def test_react_to_exception_falls_through_to_non_recoverable(self):
        """Test react_to_exception calls _handle_non_recoverable_error when recovery fails."""
        exc = RuntimeError("Fatal error")

        with (
            patch.object(
                self.service, "_try_error_recovery", new_callable=AsyncMock
            ) as mock_try,
            patch.object(
                self.service, "_handle_non_recoverable_error", new_callable=AsyncMock
            ) as mock_handle,
        ):
            mock_try.return_value = False
            await self.service.react_to_exception(exc)

        mock_handle.assert_called_once_with(exc)

    async def test_react_to_exception_sets_last_error(self):
        """Test react_to_exception sets last_error on state."""
        exc = RuntimeError("Test error message")

        with patch.object(
            self.service, "_try_error_recovery", new_callable=AsyncMock
        ) as mock_try:
            mock_try.return_value = True
            await self.service.react_to_exception(exc)

        self.mock_controller.state.set_last_error.assert_called_once()

    # ── _format_user_message ────────────────────────────────────────

    def test_format_user_message_with_llm_error(self):
        """Test _format_user_message returns LLM error message when available."""
        from backend.llm.exceptions import APIConnectionError

        exc = APIConnectionError("Connection lost")
        result = self.service._format_user_message(exc, ErrorType.NETWORK_ERROR)

        self.assertIn("API Connection Error", result)

    def test_format_user_message_with_generic_template(self):
        """Test _format_user_message uses generic template for known error types."""
        exc = RuntimeError("missing_module")
        result = self.service._format_user_message(exc, ErrorType.MODULE_NOT_FOUND)

        self.assertIn("missing", result.lower())

    def test_format_user_message_unknown_error_type(self):
        """Test _format_user_message falls back to str representation."""
        exc = RuntimeError("Custom error message")
        result = self.service._format_user_message(exc, ErrorType.UNKNOWN_ERROR)

        self.assertIn("Custom error message", result)

    # ── _format_llm_error ───────────────────────────────────────────

    def test_format_llm_error_api_connection(self):
        """Test _format_llm_error for API connection error."""
        from backend.llm.exceptions import APIConnectionError

        exc = APIConnectionError("Connection refused")
        result = self.service._format_llm_error(exc)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("API Connection Error", result)
        self.assertIn("Connection refused", result)

    def test_format_llm_error_authentication(self):
        """Test _format_llm_error for authentication error."""
        from backend.llm.exceptions import AuthenticationError

        exc = AuthenticationError("Invalid API key")
        result = self.service._format_llm_error(exc)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("Authentication Error", result)

    def test_format_llm_error_insufficient_quota(self):
        """Test _format_llm_error for billing/quota exhaustion surfaced as auth."""
        from backend.llm.exceptions import AuthenticationError

        exc = AuthenticationError(
            "429 insufficient_quota: please check your plan and billing details"
        )
        result = self.service._format_llm_error(exc)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("Billing", result)

    def test_format_llm_error_rate_limit(self):
        """Test _format_llm_error for rate limit error."""
        from backend.llm.exceptions import RateLimitError

        exc = RateLimitError("Rate limit exceeded")
        result = self.service._format_llm_error(exc)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("Rate Limit", result)

    def test_format_llm_error_generic_returns_none(self):
        """Test _format_llm_error returns None for non-LLM errors."""
        exc = RuntimeError("Generic error")
        result = self.service._format_llm_error(exc)

        self.assertIsNone(result)

    def test_format_llm_error_none_returns_none(self):
        """Test _format_llm_error returns None for None."""
        result = self.service._format_llm_error(cast(Exception, None))

        self.assertIsNone(result)

    # ── _format_rate_limit_error ────────────────────────────────────

    def test_format_rate_limit_error_quota(self):
        """Test _format_rate_limit_error detects quota exceeded."""
        from backend.llm.exceptions import RateLimitError

        exc = RateLimitError("Your free_tier quota has been exceeded")
        result = self.service._format_rate_limit_error(exc)

        self.assertIn("Quota Exceeded", result)

    def test_format_rate_limit_error_rate(self):
        """Test _format_rate_limit_error for standard rate limit."""
        from backend.llm.exceptions import RateLimitError

        exc = RateLimitError("Too many requests")
        result = self.service._format_rate_limit_error(exc)

        self.assertIn("Rate Limit Exceeded", result)

    # ── _extract_retry_delay ────────────────────────────────────────

    def test_extract_retry_delay_seconds_pattern(self):
        """Test _extract_retry_delay extracts seconds."""
        result = self.service._extract_retry_delay("retry in 38.6s")
        self.assertIn("minute", result)

    def test_extract_retry_delay_no_match(self):
        """Test _extract_retry_delay returns default for unrecognized strings."""
        result = self.service._extract_retry_delay("unknown error")
        self.assertEqual(result, "a few moments")

    def test_extract_retry_delay_minutes_pattern(self):
        """Test _extract_retry_delay extracts minutes."""
        result = self.service._extract_retry_delay("retry in 5 minutes")
        self.assertIn("5 minute", result)

    # ── _try_error_recovery ─────────────────────────────────────────

    async def test_try_error_recovery_authentication_error(self):
        """Test _try_error_recovery returns False for authentication errors."""
        from backend.llm.exceptions import AuthenticationError

        exc = AuthenticationError("Auth failed")
        result = await self.service._try_error_recovery(exc, ErrorType.UNKNOWN_ERROR)

        self.assertFalse(result)

    async def test_try_error_recovery_max_retries_exceeded(self):
        """Test _try_error_recovery returns False when max retries exceeded."""
        self.mock_retry_service.retry_count = 5

        exc = RuntimeError("Error")
        result = await self.service._try_error_recovery(exc, ErrorType.RUNTIME_CRASH)

        self.assertFalse(result)

    async def test_try_error_recovery_tool_call_error_skipped(self):
        """Test _try_error_recovery skips tool call errors after one retry."""
        self.mock_retry_service.retry_count = 1
        exc = RuntimeError("Tool error")
        result = await self.service._try_error_recovery(exc, ErrorType.TOOL_CALL_ERROR)

        self.assertFalse(result)

    async def test_try_error_recovery_tool_call_error_allows_first_retry(self):
        """Test _try_error_recovery allows a single retry for tool call errors."""
        self.mock_retry_service.retry_count = 0
        exc = RuntimeError("Tool error")
        result = await self.service._try_error_recovery(exc, ErrorType.TOOL_CALL_ERROR)

        # First attempt is allowed through (not skipped)
        self.assertTrue(result)

    async def test_try_error_recovery_with_autonomy_controller(self):
        """Test _try_error_recovery uses autonomy controller when available."""
        mock_autonomy = MagicMock()
        mock_autonomy.should_retry_on_error.return_value = True
        self.mock_controller.autonomy_controller = mock_autonomy
        self.mock_retry_service.retry_count = 0

        exc = RuntimeError("Recoverable error")

        with patch.object(
            self.service, "_execute_recovery_actions", new_callable=AsyncMock
        ):
            result = await self.service._try_error_recovery(
                exc, ErrorType.NETWORK_ERROR
            )

        self.assertTrue(result)

    async def test_try_error_recovery_no_autonomy_uses_strategy(self):
        """Test _try_error_recovery uses ErrorRecoveryStrategy when no autonomy."""
        self.mock_controller.autonomy_controller = None
        self.mock_retry_service.retry_count = 0

        exc = RuntimeError("Missing module: numpy")

        with patch(
            "backend.controller.services.recovery_service.ErrorRecoveryStrategy"
        ) as mock_strategy:
            mock_strategy.get_recovery_actions.return_value = [MagicMock()]
            with patch.object(
                self.service, "_execute_recovery_actions", new_callable=AsyncMock
            ):
                result = await self.service._try_error_recovery(
                    exc, ErrorType.MODULE_NOT_FOUND
                )

        self.assertTrue(result)

    # ── _execute_recovery_actions ───────────────────────────────────

    async def test_execute_recovery_actions_increments_retry(self):
        """Test _execute_recovery_actions increments retry count."""
        with patch(
            "backend.controller.services.recovery_service.ErrorRecoveryStrategy"
        ) as mock_strategy:
            mock_strategy.get_recovery_actions.return_value = [MagicMock()]
            self.mock_controller.state.agent_state = MagicMock()
            self.mock_controller.state.agent_state.RUNNING = (
                self.mock_controller.state.agent_state
            )

            await self.service._execute_recovery_actions(
                ErrorType.NETWORK_ERROR, RuntimeError("Network error")
            )

        self.mock_retry_service.increment_retry_count.assert_called_once()

    async def test_execute_recovery_actions_emits_events(self):
        """Test _execute_recovery_actions adds recovery events to stream."""
        mock_action = MagicMock()
        with patch(
            "backend.controller.services.recovery_service.ErrorRecoveryStrategy"
        ) as mock_strategy:
            mock_strategy.get_recovery_actions.return_value = [mock_action]
            self.mock_controller.state.agent_state = MagicMock()
            self.mock_controller.state.agent_state.RUNNING = (
                self.mock_controller.state.agent_state
            )

            await self.service._execute_recovery_actions(
                ErrorType.RUNTIME_CRASH, RuntimeError("Crash")
            )

        self.mock_controller.event_stream.add_event.assert_called()

    # ── _handle_non_recoverable_error ───────────────────────────────

    async def test_handle_non_recoverable_error_no_status_callback(self):
        """Test _handle_non_recoverable_error with no status callback."""
        self.mock_controller.status_callback = None

        exc = RuntimeError("Fatal error")
        await self.service._handle_non_recoverable_error(exc)

        self.mock_controller.circuit_breaker_service.record_error.assert_called_once_with(
            exc
        )

    async def test_handle_non_recoverable_error_with_status_callback(self):
        """Test _handle_non_recoverable_error invokes status callback."""
        self.mock_controller.status_callback = MagicMock()

        exc = RuntimeError("Fatal")
        await self.service._handle_non_recoverable_error(exc)

        self.mock_controller.status_callback.assert_called_once()

    async def test_handle_non_recoverable_error_rate_limit_with_callback(self):
        """Test _handle_non_recoverable_error routes RateLimitError to rate limit handler."""
        from backend.llm.exceptions import RateLimitError

        self.mock_controller.status_callback = MagicMock()

        exc = RateLimitError("Rate limited")

        with patch.object(
            self.service, "_handle_rate_limit_error", new_callable=AsyncMock
        ) as mock_rl:
            await self.service._handle_non_recoverable_error(exc)

        mock_rl.assert_called_once_with(exc)

    async def test_handle_non_recoverable_error_sets_error_state(self):
        """Test _handle_non_recoverable_error transitions to ERROR state."""
        from backend.core.schemas import AgentState

        self.mock_controller.status_callback = None

        exc = RuntimeError("Fatal")
        await self.service._handle_non_recoverable_error(exc)

        self.mock_controller.set_agent_state_to.assert_called_once_with(
            AgentState.ERROR
        )

    # ── _determine_runtime_status ───────────────────────────────────

    def test_determine_runtime_status_authentication(self):
        """Test _determine_runtime_status for authentication error."""
        from backend.llm.exceptions import AuthenticationError

        exc = AuthenticationError("Bad key")
        result = self.service._determine_runtime_status(exc)

        self.assertEqual(result, RuntimeStatus.ERROR_LLM_AUTHENTICATION)

    def test_determine_runtime_status_rate_limit(self):
        """Test _determine_runtime_status for rate limit error."""
        from backend.llm.exceptions import RateLimitError

        exc = RateLimitError("Rate limited")
        result = self.service._determine_runtime_status(exc)

        self.assertEqual(result, RuntimeStatus.LLM_RETRY)

    def test_determine_runtime_status_generic(self):
        """Test _determine_runtime_status for generic exception."""
        exc = RuntimeError("Generic error")
        result = self.service._determine_runtime_status(exc)

        self.assertEqual(result, RuntimeStatus.ERROR)

    def test_determine_runtime_status_api_connection(self):
        """Test _determine_runtime_status for API connection error."""
        from backend.llm.exceptions import APIConnectionError

        exc = APIConnectionError("Connection failed")
        result = self.service._determine_runtime_status(exc)

        self.assertEqual(result, RuntimeStatus.ERROR_LLM_SERVICE_UNAVAILABLE)

    def test_determine_runtime_status_service_unavailable(self):
        """Test _determine_runtime_status for service unavailable."""
        from backend.llm.exceptions import ServiceUnavailableError

        exc = ServiceUnavailableError("Service down")
        result = self.service._determine_runtime_status(exc)

        self.assertEqual(result, RuntimeStatus.ERROR_LLM_SERVICE_UNAVAILABLE)

    # ── _handle_rate_limit_error ────────────────────────────────────

    async def test_handle_rate_limit_error_retries_exhausted(self):
        """Test _handle_rate_limit_error when retries are exhausted."""
        from backend.core.schemas import AgentState

        exc = MagicMock()
        exc.retry_attempt = 5
        exc.max_retries = 3

        await self.service._handle_rate_limit_error(exc)

        self.mock_controller.set_agent_state_to.assert_called_once_with(
            AgentState.ERROR
        )

    async def test_handle_rate_limit_error_sets_rate_limited(self):
        """Test _handle_rate_limit_error sets RATE_LIMITED state."""
        from backend.core.schemas import AgentState

        exc = MagicMock(spec=["message", "__str__"])
        cast(Any, exc).__str__ = lambda self: "Rate limited"
        # No retry_attempt / max_retries attrs

        await self.service._handle_rate_limit_error(exc)

        self.mock_controller.set_agent_state_to.assert_called_once_with(
            AgentState.RATE_LIMITED
        )

    # ── _emit_recovery_event ────────────────────────────────────────

    def test_emit_recovery_event_does_not_crash(self):
        """Test _emit_recovery_event emits telemetry silently."""
        self.service._emit_recovery_event("test", error_type="UNKNOWN_ERROR")

        self.mock_context.emit_event.assert_called_once()

    def test_emit_recovery_event_handles_exception(self):
        """Test _emit_recovery_event swallows exceptions."""
        self.mock_context.emit_event.side_effect = RuntimeError("Boom")

        # Should not raise
        self.service._emit_recovery_event("test")


if __name__ == "__main__":
    unittest.main()
