"""Recover the agent loop after step-level failures (LLM, runtime)."""

from __future__ import annotations

import json
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

        self._apply_timeout_planning_routing(controller, exc)

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

    def _apply_timeout_planning_routing(self, controller, exc: Exception) -> None:
        """Route timeout recoveries based on recent MCP validation failures."""
        if not isinstance(exc, Timeout):
            return

        state = getattr(controller, "state", None)
        if state is None or not hasattr(state, "set_planning_directive"):
            return

        # Avoid clobbering any directive that is already queued for this turn.
        turn_signals = getattr(state, "turn_signals", None)
        existing = getattr(turn_signals, "planning_directive", None) if turn_signals else None
        if existing:
            return

        history = getattr(state, "history", []) or []
        recent = history[-3:] if isinstance(history, list) else []

        for event in reversed(recent):
            observation_type = str(getattr(event, "observation", "")).lower()
            content = getattr(event, "content", "")
            if not isinstance(content, str):
                continue
            if observation_type != "mcp":
                continue

            payload = None
            try:
                payload = json.loads(content)
            except Exception:
                payload = None

            if isinstance(payload, dict):
                error_code = str(payload.get("error_code") or "")
                error_text = str(payload.get("error") or "")
                if error_code == "MCP_TOOL_VALIDATION_ERROR" or "-32602" in error_text:
                    directive = (
                        "Recent MCP call failed due to tool argument validation. "
                        "Before any broad reasoning, select exactly one MCP tool, "
                        "rebuild arguments to match its schema types, and retry once. "
                        "If still invalid, explain the exact required argument shape to the user."
                    )
                    state.set_planning_directive(
                        directive,
                        source="RecoveryService.mcp_validation_timeout",
                    )
                    logger.warning(
                        "Injected planning directive after Timeout due to recent MCP validation error"
                    )
                    return

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
