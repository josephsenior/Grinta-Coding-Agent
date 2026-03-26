"""Recover the agent loop after step-level failures (LLM, runtime)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.core.errors import AgentRuntimeError, LLMContextWindowExceedError
from backend.core.logger import forge_logger as logger
from backend.events import EventSource
from backend.events.observation import ErrorObservation
from backend.llm.exceptions import (
    AuthenticationError,
    ContentPolicyViolationError,
    ContextWindowExceededError,
    Timeout,
)

if TYPE_CHECKING:
    from backend.controller.services.controller_context import ControllerContext


class RecoveryService:
    """Emits recoverable ErrorObservation, optional retry scheduling, and advances the loop."""

    def __init__(self, context: ControllerContext) -> None:
        self._context = context

    async def react_to_exception(self, exc: Exception) -> None:
        controller = self._context.get_controller()

        try:
            controller.circuit_breaker_service.record_error(exc)
        except Exception:
            logger.debug("circuit_breaker record_error failed", exc_info=True)

        pending_svc = getattr(controller, "pending_action_service", None)
        if pending_svc is not None:
            pending = pending_svc.get()
            if pending is not None:
                self._context.discard_invocation_context_for_action(pending)
                pending_svc.set(None)

        msg, err_id, notify_ui_only = self._format_exception(exc)
        self._context.emit_event(
            ErrorObservation(
                content=msg,
                error_id=err_id,
                notify_ui_only=notify_ui_only,
            ),
            EventSource.ENVIRONMENT,
        )

        retry_scheduled = False
        try:
            retry_scheduled = await controller.retry_service.schedule_retry_after_failure(
                exc
            )
        except Exception:
            logger.debug("schedule_retry_after_failure failed", exc_info=True)

        if not retry_scheduled:
            self._context.trigger_step()

    @staticmethod
    def _format_exception(exc: Exception) -> tuple[str, str, bool]:
        notify_ui_only = isinstance(
            exc,
            (AuthenticationError, ContentPolicyViolationError),
        )
        err_id = "AGENT_STEP_EXCEPTION"
        if isinstance(exc, Timeout):
            err_id = "LLM_TIMEOUT"
        elif isinstance(exc, LLMContextWindowExceedError | ContextWindowExceededError):
            err_id = "LLM_CONTEXT_WINDOW_EXCEEDED"
        elif isinstance(exc, AgentRuntimeError):
            err_id = "AGENT_RUNTIME_ERROR"

        text = f"{type(exc).__name__}: {exc}"
        guidance = (
            "The agent step failed with the error above. Adjust strategy "
            "(different tool, smaller change, or confirm configuration) and continue."
        )
        return f"{text}\n\n{guidance}", err_id, notify_ui_only
