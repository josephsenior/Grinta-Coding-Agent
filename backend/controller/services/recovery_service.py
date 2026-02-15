from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from backend.controller.error_recovery import ErrorRecoveryStrategy, ErrorType
from backend.core.logger import FORGE_logger as logger
from backend.core.schemas import AgentState
from backend.events import EventSource
from backend.events.observation import AgentThinkObservation
from backend.core.enums import RuntimeStatus

if TYPE_CHECKING:
    from backend.controller.services.controller_context import ControllerContext
    from backend.controller.services.retry_service import RetryService


class RecoveryService:
    """Centralizes exception classification, retry orchestration, and recovery actions."""

    def __init__(
        self,
        context: ControllerContext,
        retry_service: RetryService,
        *,
        max_retries: int = 3,
    ) -> None:
        self._context = context
        self._retry_service = retry_service
        self._max_retries = max_retries

    async def react_to_exception(self, exc: Exception) -> None:
        controller = self._context.get_controller()
        controller.log(
            "error",
            f"_react_to_exception called with: {type(exc).__name__}: {exc}",
        )
        error_type = ErrorRecoveryStrategy.classify_error(exc)
        controller.state.set_last_error(
            self._format_user_message(exc, error_type), source="RecoveryService"
        )
        controller.log("info", f"Set error message: {controller.state.last_error}")
        self._emit_recovery_event(
            "start",
            error_type=error_type.value,
            user_message=controller.state.last_error,
        )

        attempted = await self._try_error_recovery(exc, error_type)
        if attempted:
            return

        await self._handle_non_recoverable_error(exc)

    _GENERIC_MESSAGES = {
        ErrorType.MODULE_NOT_FOUND: "A required Python module is missing: {message}",
        ErrorType.RUNTIME_CRASH: "The runtime appears to have crashed or disconnected. Reinitializing environment.",
        ErrorType.NETWORK_ERROR: "Network connectivity issue detected. The agent will retry once connectivity is restored.",
        ErrorType.FILESYSTEM_ERROR: "File system error encountered. Please check paths and permissions.",
        ErrorType.TOOL_CALL_ERROR: "Tool invocation failed because of invalid arguments. Review the last tool call and retry.",
        ErrorType.TIMEOUT_ERROR: "A step timed out before completion. Consider splitting the task or increasing the timeout.",
        ErrorType.PERMISSION_ERROR: "Operation failed due to insufficient permissions.",
        ErrorType.DISK_FULL_ERROR: "The workspace disk appears full. Free up space and retry.",
    }

    def _format_user_message(self, exc: Exception, error_type: ErrorType) -> str:
        llm_message = self._format_llm_error(exc)
        if llm_message:
            return llm_message

        template = self._GENERIC_MESSAGES.get(error_type)
        if template:
            return template.format(message=str(exc))

        return f"{type(exc).__name__}: {exc!s}"

    def _format_llm_error(self, exc: Exception) -> str | None:
        from backend.llm.exceptions import (
            APIConnectionError,
            AuthenticationError,
            RateLimitError,
        )

        if isinstance(exc, APIConnectionError):
            return (
                f"⚠️ API Connection Error\n\n"
                f"Unable to connect to the AI service. This usually means:\n\n"
                f"• The AI service is temporarily unavailable\n"
                f"• There's a network connectivity issue\n"
                f"• The service is experiencing high load\n\n"
                f"**What you can do:**\n"
                f"• Wait a moment and try again\n"
                f"• Check your internet connection\n"
                f"• Try using a different AI model\n\n"
                f"**Technical details:** {exc}"
            )
        if isinstance(exc, AuthenticationError):
            return (
                f"🔒 Authentication Error\n\n"
                f"There's an issue with your API key configuration.\n\n"
                f"**What you can do:**\n"
                f"• Check that your API key is correct in settings\n"
                f"• Verify the API key has the necessary permissions\n"
                f"• Ensure the API key hasn't expired or been revoked\n"
                f"• Try regenerating your API key\n\n"
                f"**Technical details:** {exc}"
            )
        if isinstance(exc, RateLimitError):
            return self._format_rate_limit_error(exc)
        return None

    def _format_rate_limit_error(self, exc: Exception) -> str:
        """Format an LLM rate limit or quota exceeded error."""
        error_str = str(exc)
        time_until_reset = self._extract_retry_delay(error_str)

        # Detect if it's a quota vs rate limit issue
        is_quota = "quota" in error_str.lower() or "free_tier" in error_str.lower()

        if is_quota:
            return (
                f"💰 API Quota Exceeded\n\n"
                f"You've reached your API quota limit for this AI model.\n\n"
                f"**Your quota resets in:** {time_until_reset}\n\n"
                f"**What you can do:**\n"
                f"• Wait {time_until_reset} for the quota to reset\n"
                f"• Use a different AI model (if available)\n"
                f"• Upgrade your API plan for higher limits\n"
                f"• Check your API provider's usage dashboard\n\n"
                f"**Note:** This is an API provider limit, not a Forge limit."
            )

        return (
            f"⏰ Rate Limit Exceeded\n\n"
            f"You're sending requests too quickly. The AI service has rate limits to ensure fair usage.\n\n"
            f"**Retry in:** {time_until_reset}\n\n"
            f"**What you can do:**\n"
            f"• Wait {time_until_reset} before trying again\n"
            f"• Slow down your request rate\n"
            f"• Use a different AI model (if available)\n"
            f"• Upgrade your API plan for higher rate limits\n\n"
            f"**Note:** This is an API provider rate limit, not a Forge limit."
        )

    def _extract_retry_delay(self, error_str: str) -> str:
        """Extract retry delay from error message if available."""
        import re

        time_until_reset = "a few moments"
        patterns = [
            r"retry\s+(?:in|after)\s+(\d+(?:\.\d+)?)\s*s",  # "retry in 38.6s"
            r"retry\s+(?:in|after)\s+(\d+)\s*second",  # "retry after 30 seconds"
            r"retry\s+(?:in|after)\s+(\d+)\s*minute",  # "retry in 5 minutes"
            r"(\d+(?:\.\d+)?)\s*second",  # "38.613643389s"
        ]

        for pattern in patterns:
            match = re.search(pattern, error_str, re.IGNORECASE)
            if match:
                try:
                    retry_delay = int(float(match.group(1)))
                    if "minute" in pattern:
                        return f"{retry_delay} minute{'s' if retry_delay != 1 else ''}"
                    minutes = max(1, retry_delay // 60)
                    if minutes > 0:
                        return f"{minutes} minute{'s' if minutes != 1 else ''}"
                    return f"{retry_delay} second{'s' if retry_delay != 1 else ''}"
                except (ValueError, AttributeError):
                    continue
        return time_until_reset

    async def _try_error_recovery(self, exc: Exception, error_type: ErrorType) -> bool:
        from backend.llm.exceptions import AuthenticationError

        controller = self._context.get_controller()

        if isinstance(exc, AuthenticationError):
            controller.log(
                "info",
                "Skipping error recovery for AuthenticationError - requires user intervention",
            )
            self._emit_recovery_event(
                "skipped", error_type=error_type.value, reason="authentication_error"
            )
            return False

        if self._retry_service.retry_count >= self._max_retries:
            controller.log(
                "warning",
                f"Maximum retry limit ({self._max_retries}) reached for error: {type(exc).__name__}",
            )
            self._emit_recovery_event(
                "skipped", error_type=error_type.value, reason="max_retries"
            )
            return False

        if error_type == ErrorType.TOOL_CALL_ERROR:
            logger.info(
                "Skipping recovery for tool call error to prevent infinite loop"
            )
            self._emit_recovery_event(
                "skipped", error_type=error_type.value, reason="tool_call_error"
            )
            return False

        autonomy = getattr(controller, "autonomy_controller", None)
        if autonomy and autonomy.should_retry_on_error(
            exc, self._retry_service.retry_count
        ):
            await self._execute_recovery_actions(error_type, exc)
            return True

        if error_type != ErrorType.UNKNOWN_ERROR:
            recovery_actions = ErrorRecoveryStrategy.get_recovery_actions(
                error_type, exc
            )
            if recovery_actions:
                await self._execute_recovery_actions(error_type, exc)
                return True

        return False

    async def _execute_recovery_actions(
        self, error_type: ErrorType, exc: Exception
    ) -> None:
        controller = self._context.get_controller()

        logger.info(
            "Auto-recovery for %s: attempt %s",
            error_type,
            self._retry_service.retry_count + 1,
        )
        recovery_actions = ErrorRecoveryStrategy.get_recovery_actions(error_type, exc)
        for action in recovery_actions:
            controller.event_stream.add_event(action, EventSource.AGENT)

        self._retry_service.increment_retry_count()

        if not recovery_actions:
            logger.info(
                "No recovery actions available for %s, skipping retry to prevent infinite loop",
                error_type,
            )
            return

        self._emit_recovery_event(
            "retry_scheduled",
            error_type=error_type.value,
            actions=[type(action).__name__ for action in recovery_actions],
            attempt=self._retry_service.retry_count,
        )

        if (
            controller.state.agent_state == controller.state.agent_state.RUNNING  # type: ignore[attr-defined]
            and self._retry_service.retry_count <= self._max_retries
        ):
            await asyncio.sleep(2**self._retry_service.retry_count)
            if error_type == ErrorType.TOOL_CALL_ERROR:
                logger.info(
                    "Tool call error recovery: allowing time for user to review and potentially fix the issue"
                )
                await asyncio.sleep(3)
            controller.step()
        else:
            if self._retry_service.retry_count > self._max_retries:
                logger.warning(
                    "Reached maximum retry limit (%s), stopping recovery attempt",
                    self._retry_service.retry_count,
                )

    async def _handle_non_recoverable_error(self, exc: Exception) -> None:
        from backend.events.observation import ErrorObservation

        controller = self._context.get_controller()
        logger.error(
            "Non-recoverable error encountered: %s. Transitioning to ERROR state.", exc
        )
        self._context.get_controller().circuit_breaker_service.record_error(exc)
        error_type = ErrorRecoveryStrategy.classify_error(exc)

        runtime_status = None
        if controller.status_callback is not None:
            runtime_status = self._determine_runtime_status(exc)
            if runtime_status == RuntimeStatus.ERROR_LLM_OUT_OF_CREDITS:
                await self._handle_rate_limit_error(exc)
                return

            # Check if it's a RateLimitError that should be handled
            from backend.llm.exceptions import RateLimitError

            if isinstance(exc, RateLimitError):
                await self._handle_rate_limit_error(exc)
                return
            controller.status_callback(
                "error", runtime_status, controller.state.last_error
            )
        else:
            runtime_status = self._determine_runtime_status(exc)

        self._emit_recovery_event(
            "non_recoverable",
            error_type=error_type.value,
            runtime_status=runtime_status.value if runtime_status else None,
            user_message=controller.state.last_error,
        )

        if await self._retry_service.schedule_retry_after_failure(exc):
            await controller.set_agent_state_to(AgentState.PAUSED)
            self._emit_recovery_event(
                "retry_deferred", next_state=AgentState.PAUSED.value
            )
            return

        # Send user-friendly error message to client before setting ERROR state
        error_message = (
            controller.state.last_error or f"An error occurred: {type(exc).__name__}"
        )

        # Log to audit store
        await controller.log_task_audit("FAILURE", error_message=error_message)

        error_obs = ErrorObservation(
            content=error_message,
            error_id=error_type.value.upper() if error_type else "UNKNOWN_ERROR",
        )
        controller.event_stream.add_event(error_obs, EventSource.AGENT)

        await controller.set_agent_state_to(AgentState.ERROR)
        self._emit_recovery_event("halted", next_state=AgentState.ERROR.value)

    def _determine_runtime_status(self, exc: Exception) -> RuntimeStatus:
        from backend.llm.exceptions import (
            APIConnectionError,
            APIError,
            AuthenticationError,
            BadRequestError,
            ContentPolicyViolationError,
            InternalServerError,
            RateLimitError,
            ServiceUnavailableError,
        )

        if isinstance(exc, AuthenticationError):
            return RuntimeStatus.ERROR_LLM_AUTHENTICATION
        if isinstance(exc, (ServiceUnavailableError, APIConnectionError, APIError)):
            return RuntimeStatus.ERROR_LLM_SERVICE_UNAVAILABLE
        if isinstance(exc, InternalServerError):
            return RuntimeStatus.ERROR_LLM_INTERNAL_SERVER_ERROR
        if isinstance(exc, BadRequestError) and "ExceededBudget" in str(exc):
            return RuntimeStatus.ERROR_LLM_OUT_OF_CREDITS
        if isinstance(exc, ContentPolicyViolationError) or (
            isinstance(exc, BadRequestError)
            and "ContentPolicyViolationError" in str(exc)
        ):
            return RuntimeStatus.ERROR_LLM_CONTENT_POLICY_VIOLATION
        if isinstance(exc, RateLimitError):
            return RuntimeStatus.LLM_RETRY
        return RuntimeStatus.ERROR

    async def _handle_rate_limit_error(self, exc: Exception) -> None:
        from backend.events.observation import ErrorObservation

        controller = self._context.get_controller()
        if (
            hasattr(exc, "retry_attempt")
            and hasattr(exc, "max_retries")
            and (exc.retry_attempt >= exc.max_retries)
        ):
            # Retries exhausted - send user-friendly error message
            error_message = self._format_llm_error(exc) or str(exc)

            # Log to audit store
            await controller.log_task_audit(
                "FAILURE", error_message=f"Rate limit exceeded: {error_message}"
            )

            error_obs = ErrorObservation(
                content=error_message,
                error_id="RATE_LIMIT_EXCEEDED",
            )
            controller.event_stream.add_event(error_obs, EventSource.AGENT)

            controller.state.set_last_error(
                RuntimeStatus.AGENT_RATE_LIMITED_STOPPED_MESSAGE.value,
                source="RecoveryService.rate_limit",
            )
            await controller.set_agent_state_to(AgentState.ERROR)
            self._emit_recovery_event("halted", next_state=AgentState.ERROR.value)
        else:
            await controller.set_agent_state_to(AgentState.RATE_LIMITED)
            self._emit_recovery_event(
                "rate_limited", next_state=AgentState.RATE_LIMITED.value
            )

    def _emit_recovery_event(self, stage: str, **payload: Any) -> None:
        """Emit structured telemetry for recovery flow."""
        parts = [
            f"stage={stage}",
            f"retry={self._retry_service.retry_count}",
        ]
        if payload:
            parts.append(f"payload={payload}")
        message = "[Recovery] " + " ".join(parts)
        event = AgentThinkObservation(content=message)
        try:
            self._context.emit_event(event, EventSource.ENVIRONMENT)
        except Exception:  # pragma: no cover - telemetry must not break recovery
            logger.debug("Failed to emit recovery telemetry", exc_info=True)
