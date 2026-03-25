"""Handles action retrieval and execution steps for AgentController."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.core.logger import forge_logger as logger
from backend.core.errors import (
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
    BadRequestError,
    ContextWindowExceededError,
    OpenAIError,
    Timeout,
    is_context_window_error,
)

if TYPE_CHECKING:
    from backend.controller.services.controller_context import ControllerContext
    from backend.controller.tool_pipeline import ToolInvocationContext
    from backend.events.action import Action


def _resolve_llm_step_timeout_seconds(agent) -> float | None:
    """Per-LLM-step cap for ``astep`` only.

    ``None`` means no ``asyncio.wait_for`` limit (model may stream as long as needed).
    Set ``agent.config.llm_step_timeout_seconds`` to a positive number, or
    ``FORGE_LLM_STEP_TIMEOUT_SECONDS`` to a positive value, to enforce a cap.
    Zero, negative, or empty/unset env leaves the step uncapped.
    """
    from backend.core.llm_step_timeout import llm_step_timeout_seconds_from_env

    cfg = getattr(agent, "config", None)
    if cfg is not None:
        v = getattr(cfg, "llm_step_timeout_seconds", None)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            f = float(v)
            return None if f <= 0 else f
    return llm_step_timeout_seconds_from_env()


class ActionExecutionService:
    """Encapsulates action acquisition, planning, and execution orchestration."""

    def __init__(self, context: ControllerContext) -> None:
        self._context = context

    async def get_next_action(self) -> Action | None:
        """Get the next action from the agent, with automatic repair for validation errors."""
        max_repair_attempts = 3

        error_logged = False
        for attempt in range(max_repair_attempts + 1):
            try:
                confirmation = self._context.confirmation_service
                controller = self._context.get_controller()
                replay_mgr = getattr(controller, "_replay_manager", None)
                # ConfirmationService.get_next_action() uses synchronous agent.step()
                # for live runs, which disables real token streaming (astep/async_execute).
                # Only delegate there during trajectory replay; otherwise prefer astep.
                use_confirmation_replay = (
                    confirmation is not None
                    and replay_mgr is not None
                    and replay_mgr.should_replay() is True
                )
                if use_confirmation_replay:
                    action = confirmation.get_next_action()
                else:
                    # Prefer the async step path (real LLM streaming) when
                    # available; fall back to synchronous step() otherwise.
                    import asyncio as _asyncio

                    agent = self._context.agent
                    astep = getattr(agent, "astep", None)
                    if astep is not None and _asyncio.iscoroutinefunction(astep):
                        logger.info(
                            "ActionExecutionService.get_next_action: invoking astep "
                            "for agent=%s (attempt=%d)",
                            getattr(agent, "name", agent.__class__.__name__),
                            attempt,
                        )
                        timeout = _resolve_llm_step_timeout_seconds(agent)
                        if timeout is None:
                            action = await astep(self._context.state)
                        else:
                            # Retry once on timeout before propagating
                            for _timeout_attempt in range(2):
                                try:
                                    action = await _asyncio.wait_for(
                                        astep(self._context.state),
                                        timeout=timeout,
                                    )
                                    break  # success
                                except _asyncio.TimeoutError as exc:
                                    if _timeout_attempt == 0:
                                        logger.warning(
                                            "ActionExecutionService.get_next_action: "
                                            "astep timed out after %s seconds, retrying once",
                                            timeout,
                                        )
                                        continue
                                    model_name = None
                                    try:
                                        llm = getattr(agent, "llm", None)
                                        model_name = getattr(
                                            getattr(llm, "config", None), "model", None
                                        )
                                    except Exception:
                                        pass
                                    logger.error(
                                        "ActionExecutionService.get_next_action: astep timed out "
                                        "after %s seconds for model=%s (after retry)",
                                        timeout,
                                        model_name,
                                    )
                                    raise Timeout(
                                        f"LLM step timed out after {timeout} seconds",
                                        model=model_name,
                                    ) from exc
                    else:
                        action = agent.step(self._context.state)
                action.source = EventSource.AGENT

                logger.info(
                    "ActionExecutionService.get_next_action: obtained action=%s "
                    "from agent=%s",
                    getattr(action, "action", type(action).__name__),
                    getattr(self._context.agent, "name", self._context.agent.__class__.__name__),
                )
                return action

            except (
                LLMMalformedActionError,
                LLMNoActionError,
                LLMResponseError,
                FunctionCallValidationError,
                FunctionCallNotExistsError,
            ) as exc:
                # Create detailed error observation
                error_msg = str(exc)
                if isinstance(exc, FunctionCallValidationError):
                    error_msg = f"Tool validation failed: {exc}\nPlease correct the tool arguments and try again."
                if isinstance(exc, FunctionCallNotExistsError):
                    error_msg = f"Tool not found: {exc}\nPlease use an existing tool from the provided list."

                obs = ErrorObservation(content=error_msg)
                if not error_logged:
                    # Add to event stream so it's recorded in history
                    self._context.event_stream.add_event(obs, EventSource.AGENT)
                    error_logged = True

                # If we have retries left, continue loop to let agent see error and try again
                if attempt < max_repair_attempts:
                    # We need to ensure the state is updated with this new observation
                    # before the next step. The state tracker updates via event subscription,
                    # but we can also manually ensure it's in the current view if needed.
                    # Typically, event_stream.add_event triggers the subscribers.
                    # We yield control briefly to allow state update to propagate if async.
                    import asyncio
                    await asyncio.sleep(0.01)
                    continue

                # If out of retries, transition to ERROR so the agent doesn't
                # stay stuck in RUNNING state indefinitely.
                from backend.core.schemas import AgentState as _AgentState
                controller = self._context.get_controller()
                if controller.get_agent_state() == _AgentState.RUNNING:
                    logger.error(
                        "get_next_action exhausted %d repair attempts; "
                        "transitioning to ERROR state",
                        max_repair_attempts,
                    )
                    await controller.set_agent_state_to(_AgentState.ERROR)
                return None

            except (ContextWindowExceededError, BadRequestError, OpenAIError) as exc:
                return await self._handle_context_window_error(exc)
            # APIConnectionError, AuthenticationError, RateLimitError, ServiceUnavailableError,
            # APIError, InternalServerError, Timeout: let propagate to caller

        return None

    async def execute_action(self, action: Action) -> None:
        # Plugin hook: action_pre
        try:
            from backend.core.plugin import get_plugin_registry

            action = await get_plugin_registry().dispatch_action_pre(action)
        except Exception as exc:
            logger.warning(
                "ActionExecutionService action_pre hook failed for %s: %s",
                type(action).__name__,
                exc,
                exc_info=True,
            )

        ctx: ToolInvocationContext | None = None
        pipeline = self._context.tool_pipeline
        if action.runnable and pipeline:
            ctx = pipeline.create_context(action, self._context.state)
            if ctx is not None:
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
