"""Handles action retrieval and execution steps for AgentController."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.core.exceptions import (
    FunctionCallNotExistsError,
    FunctionCallValidationError,
    LLMContextWindowExceedError,
    LLMMalformedActionError,
    LLMNoActionError,
    LLMResponseError,
)
from backend.events import EventSource
from backend.events.action.agent import CondensationRequestAction
from backend.events.observation import ErrorObservation
from backend.llm.exceptions import (
    APIConnectionError,
    APIError,
    AuthenticationError,
    BadRequestError,
    ContextWindowExceededError,
    InternalServerError,
    OpenAIError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
    is_context_window_error,
)

if TYPE_CHECKING:
    from backend.controller.services.controller_context import ControllerContext
    from backend.controller.tool_pipeline import ToolInvocationContext
    from backend.events.action import Action


class ActionExecutionService:
    """Encapsulates action acquisition, planning, and execution orchestration."""

    def __init__(self, context: ControllerContext) -> None:
        self._context = context

    async def get_next_action(self) -> Action | None:
        try:
            confirmation = self._context.confirmation_service
            if confirmation:
                return confirmation.get_next_action()
            action = self._context.agent.step(self._context.state)
            action.source = EventSource.AGENT
            return action
        except (
            LLMMalformedActionError,
            LLMNoActionError,
            LLMResponseError,
            FunctionCallValidationError,
            FunctionCallNotExistsError,
        ) as exc:
            self._context.event_stream.add_event(
                ErrorObservation(content=str(exc)), EventSource.AGENT
            )
            return None
        except (ContextWindowExceededError, BadRequestError, OpenAIError) as exc:
            return await self._handle_context_window_error(exc)
        except (
            APIConnectionError,
            AuthenticationError,
            RateLimitError,
            ServiceUnavailableError,
            APIError,
            InternalServerError,
            Timeout,
        ):
            raise

    async def execute_action(self, action: Action) -> None:
        # Plugin hook: action_pre
        try:
            from backend.core.plugin import get_plugin_registry

            action = await get_plugin_registry().dispatch_action_pre(action)
        except Exception:  # noqa: BLE001 — plugins must not break the pipeline
            pass

        ctx: ToolInvocationContext | None = None
        pipeline = self._context.tool_pipeline
        if action.runnable and pipeline:
            ctx = pipeline.create_context(action, self._context.state)
            self._context.register_action_context(action, ctx)
            await pipeline.run_plan(ctx)
            await self._context.iteration_service.apply_dynamic_iterations(ctx)
            if ctx.blocked:
                self._context.telemetry_service.handle_blocked_invocation(action, ctx)
                return
        await self._context.run_action(action, ctx)

    async def _handle_context_window_error(self, exc: Exception) -> Action | None:
        error_str = str(exc).lower()
        if not is_context_window_error(error_str, exc):
            raise exc
        if not self._context.agent.config.enable_history_truncation:
            raise LLMContextWindowExceedError from exc
        self._context.event_stream.add_event(
            CondensationRequestAction(), EventSource.AGENT
        )
        return None
