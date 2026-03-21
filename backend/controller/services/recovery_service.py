from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from backend.controller.error_recovery import ErrorRecoveryStrategy, ErrorType
from backend.core.logger import forge_logger as logger
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
        ErrorType.MODULE_NOT_FOUND: ("A required Python module is missing: {message}"),
        ErrorType.RUNTIME_CRASH: (
            "The runtime appears to have crashed or disconnected. "
            "Reinitializing environment."
        ),
        ErrorType.NETWORK_ERROR: (
            "Network connectivity issue detected. The agent will retry "
            "once connectivity is restored."
        ),
        ErrorType.FILESYSTEM_ERROR: (
            "File system error encountered. Please check paths and permissions."
        ),
        ErrorType.TOOL_CALL_ERROR: (
            "Tool invocation failed because of invalid arguments. "
            "Review the last tool call and retry."
        ),
        ErrorType.TIMEOUT_ERROR: (
            "A step timed out before completion. Consider splitting the "
            "task or increasing the timeout."
        ),
        ErrorType.PERMISSION_ERROR: (
            "Operation failed due to insufficient permissions."
        ),
        ErrorType.DISK_FULL_ERROR: (
            "The workspace disk appears full. Free up space and retry."
        ),
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
            Timeout,
        )

        if isinstance(exc, Timeout):
            return (
                "Request timed out\n\n"
                "The model took too long to respond (e.g. network or overload).\n\n"
                "**What you can do:**\n"
                "• Try again in a moment\n"
                "• Increase timeout via FORGE_LLM_STEP_TIMEOUT_SECONDS (default 180s)\n"
                "• Try a different model if the current one is slow\n\n"
                f"**Details:** {exc}"
            )
        if isinstance(exc, APIConnectionError):
            return (
                "API Connection Error\n\n"
                "Unable to connect to the AI service. This usually means:\n\n"
                "• The AI service is temporarily unavailable\n"
                "• There's a network connectivity issue\n"
                "• The service is experiencing high load\n\n"
                "**What you can do:**\n"
                "• Wait a moment and try again\n"
                "• Check your internet connection\n"
                "• Try using a different AI model\n\n"
                f"**Technical details:** {exc}"
            )
        if isinstance(exc, AuthenticationError):
            if self._is_billing_or_quota_error(exc):
                return (
                    "Billing / Quota Exceeded\n\n"
                    "Your API key appears to be accepted, but your account has no available quota/credits for this model.\n\n"
                    "**What you can do:**\n"
                    "• Add credits / enable billing with your provider\n"
                    "• Check your provider usage & limits dashboard\n"
                    "• Try a different model/provider with available quota\n\n"
                    f"**Technical details:** {exc}"
                )
            return (
                "Authentication Error\n\n"
                "There's an issue with your API key configuration.\n\n"
                "**What you can do:**\n"
                "• Check that your API key is correct in settings\n"
                "• Verify the API key has the necessary permissions\n"
                "• Ensure the API key hasn't expired or been revoked\n"
                "• Try regenerating your API key\n\n"
                f"**Technical details:** {exc}"
            )
        if isinstance(exc, RateLimitError):
            # Some providers report billing/quota exhaustion as HTTP 429.
            # This is not transient and should not be treated as a retryable
            # rate limit.
            if self._is_billing_or_quota_error(exc):
                return (
                    "Billing / Quota Exceeded\n\n"
                    "Your API key appears to be accepted, but your account has no available quota/credits for this model.\n\n"
                    "**What you can do:**\n"
                    "• Add credits / enable billing with your provider\n"
                    "• Check your provider usage & limits dashboard\n"
                    "• Try a different model/provider with available quota\n\n"
                    f"**Technical details:** {exc}"
                )
            return self._format_rate_limit_error(exc)
        return None

    def _is_billing_or_quota_error(self, exc: Exception) -> bool:
        """Best-effort detection for billing/quota exhaustion.

        Some providers return quota exhaustion (e.g. OpenAI "insufficient_quota")
        but it's not fixable by retries and should be shown as out-of-credits.
        """
        if self._check_structured_billing_error(exc):
            return True
        return self._check_message_billing_patterns(str(exc).lower())

    def _check_structured_billing_error(self, exc: Exception) -> bool:
        """Check structured provider hints (kwargs, body, code)."""
        kwargs = self._get_exc_kwargs(exc)
        if self._is_insufficient_quota_code(
            kwargs.get("code") or getattr(exc, "code", None)
        ):
            return True
        body = kwargs.get("body") or getattr(exc, "body", None)
        return self._check_error_body_for_billing(body)

    @staticmethod
    def _is_insufficient_quota_code(code: Any) -> bool:
        return isinstance(code, str) and code.lower() == "insufficient_quota"

    def _check_error_body_for_billing(self, body: Any) -> bool:
        """Check error body dict for billing/quota indicators."""
        if not isinstance(body, dict):
            return False
        err = body.get("error")
        if not isinstance(err, dict):
            return False
        err_code = err.get("code") or err.get("type")
        if self._is_insufficient_quota_code(err_code):
            return True
        err_message = err.get("message")
        return (
            isinstance(err_message, str)
            and err_message
            and self._check_message_billing_patterns(err_message.lower())
        )

    @staticmethod
    def _get_exc_kwargs(exc: Exception) -> dict[str, Any]:
        """Extract kwargs from exception (LLMError stores extras there)."""
        try:
            raw = getattr(exc, "kwargs", None)
            return raw if isinstance(raw, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _check_message_billing_patterns(lowered: str) -> bool:
        """Check if message contains billing/quota exhaustion patterns."""
        return (
            "insufficient_quota" in lowered
            or "exceeded your current quota" in lowered
            or "billing details" in lowered
            or "check your plan" in lowered
            or ("billing" in lowered and "quota" in lowered)
        )

    def _format_rate_limit_error(self, exc: Exception) -> str:
        """Format an LLM rate limit or quota exceeded error."""
        error_str = str(exc)
        time_until_reset = self._extract_retry_delay(error_str)

        # Detect if it's a quota vs rate limit issue
        lowered = error_str.lower()
        is_quota = (
            "quota" in lowered
            or "free_tier" in lowered
            or "insufficient_quota" in lowered
            or "exceededbudget" in lowered
        )

        if is_quota:
            return (
                "API Quota Exceeded\n\n"
                f"You've reached your API quota limit for this AI model.\n\n"
                f"**Your quota resets in:** {time_until_reset}\n\n"
                "**What you can do:**\n"
                f"• Wait {time_until_reset} for the quota to reset\n"
                "• Use a different AI model (if available)\n"
                "• Upgrade your API plan for higher limits\n"
                "• Check your API provider's usage dashboard\n\n"
                "**Note:** This is an API provider limit, not a Forge limit."
            )

        return (
            "Rate Limit Exceeded\n\n"
            "You're sending requests too quickly. The AI service has rate limits to ensure fair usage.\n\n"
            f"**Retry in:** {time_until_reset}\n\n"
            "**What you can do:**\n"
            f"• Wait {time_until_reset} before trying again\n"
            "• Slow down your request rate\n"
            "• Use a different AI model (if available)\n"
            "• Upgrade your API plan for higher rate limits\n\n"
            "**Note:** This is an API provider rate limit, not a Forge limit."
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
            if self._retry_service.retry_count >= 1:
                logger.info(
                    "Skipping recovery for tool call error — already retried once"
                )
                self._emit_recovery_event(
                    "skipped", error_type=error_type.value, reason="tool_call_retry_exhausted"
                )
                return False
            # Allow one retry: the LLM can self-correct from the error feedback
            logger.info("Allowing single retry for tool call error")
            await self._execute_recovery_actions(error_type, exc)
            return True

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
                # Fail fast: out-of-credits requires user intervention and
                # should not enter rate-limited retry state.
                controller.status_callback(
                    "error", runtime_status, controller.state.last_error
                )
            else:
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

        if (
            runtime_status != RuntimeStatus.ERROR_LLM_OUT_OF_CREDITS
            and await self._retry_service.schedule_retry_after_failure(exc)
        ):
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

        notify_ui_only = self._format_llm_error(exc) is not None
        error_obs = ErrorObservation(
            content=error_message,
            error_id=error_type.value.upper() if error_type else "UNKNOWN_ERROR",
            notify_ui_only=notify_ui_only,
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
            if self._is_billing_or_quota_error(exc):
                return RuntimeStatus.ERROR_LLM_OUT_OF_CREDITS
            return RuntimeStatus.ERROR_LLM_AUTHENTICATION
        if isinstance(exc, ServiceUnavailableError | APIConnectionError | APIError):
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
            if self._is_billing_or_quota_error(exc):
                return RuntimeStatus.ERROR_LLM_OUT_OF_CREDITS
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
                notify_ui_only=True,
            )
            controller.event_stream.add_event(error_obs, EventSource.AGENT)

            controller.state.set_last_error(
                RuntimeStatus.AGENT_RATE_LIMITED_STOPPED_MESSAGE.value,
                source="RecoveryService.rate_limit",
            )
            await controller.set_agent_state_to(AgentState.ERROR)
            self._emit_recovery_event("halted", next_state=AgentState.ERROR.value)
        else:
            # Provide a user-visible status update while in RATE_LIMITED so the
            # UI / harness can surface the cause (retry-after, quota messaging, etc.).
            try:
                msg = self._format_llm_error(exc) or str(exc)
                if controller.status_callback is not None:
                    controller.status_callback("info", RuntimeStatus.LLM_RETRY, msg)
            except Exception:
                pass
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
