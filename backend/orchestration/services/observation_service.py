from __future__ import annotations

import copy
import os
from typing import TYPE_CHECKING, Any

from backend.orchestration.state.state import AgentState
from backend.core.logger import app_logger as logger
from backend.ledger import EventSource
from backend.ledger.observation import ErrorObservation, Observation
from backend.ledger.serialization.event import truncate_content

if TYPE_CHECKING:
    from backend.orchestration.services.orchestration_context import OrchestrationContext
    from backend.orchestration.services.pending_action_service import OpenOperationService
    from backend.orchestration.tool_pipeline import ToolInvocationContext


async def transition_agent_state_logic(
    controller: Any,
    ctx: ToolInvocationContext | None,
    observation: Observation,
) -> None:
    """Shared state transition logic for agent observations."""
    if controller.state.agent_state == AgentState.USER_CONFIRMED:
        await controller.set_agent_state_to(AgentState.RUNNING)
    elif controller.state.agent_state == AgentState.USER_REJECTED:
        await controller.set_agent_state_to(AgentState.AWAITING_USER_INPUT)

    pipeline = getattr(controller, "tool_pipeline", None)
    if ctx and pipeline:
        await pipeline.run_observe(ctx, observation)
        if getattr(ctx, "blocked", False) is True:
            telemetry = getattr(controller, "telemetry_service", None)
            if telemetry is not None:
                telemetry.handle_blocked_invocation(ctx.action, ctx)
            return
        controller._cleanup_action_context(ctx)


class ObservationService:
    """Handles observation logging, metrics preparation, and pending-action observation flow."""

    def __init__(
        self,
        context: OrchestrationContext,
        open_operation_service: OpenOperationService,
    ) -> None:
        self._context = context
        self._pending_service = open_operation_service

    async def handle_observation(self, observation: Observation) -> None:
        controller = self._context.get_controller()
        observation_to_print = self._prepare_observation_for_logging(observation)
        log_level = self._get_log_level()
        controller.log(
            log_level, str(observation_to_print), extra={"msg_type": "OBSERVATION"}
        )
        await self._handle_pending_action_observation(observation)

    async def _handle_pending_action_observation(
        self, observation: Observation
    ) -> None:
        controller = self._context.get_controller()
        pending_action = self._pending_service.get()
        if not self._matches_pending_action(pending_action, observation):
            if observation.cause is not None:
                self._report_pending_action_mismatch(
                    controller,
                    pending_action=pending_action,
                    observation=observation,
                )
                if pending_action is not None:
                    await self._recover_from_pending_observation_mismatch(
                        observation, pending_action
                    )
            return

        # Plugin hook: action_post
        assert pending_action is not None  # _matches_pending_action requires this
        try:
            from backend.core.plugin import get_plugin_registry

            observation = await get_plugin_registry().dispatch_action_post(
                pending_action, observation
            )
        except Exception as exc:
            logger.warning(
                "ObservationService action_post hook failed for %s: %s",
                type(pending_action).__name__,
                exc,
                exc_info=True,
            )

        if controller.state.agent_state == AgentState.AWAITING_USER_CONFIRMATION:
            return

        ctx: ToolInvocationContext | None = None
        if observation.cause is not None:
            ctx = self._context.pop_action_context(observation.cause)

        self._pending_service.set(None)

        # Inform the hallucination detector that this file operation actually happened.
        # This feeds the state-based verification layer so it can distinguish real
        # file edits from hallucinated ones in subsequent turns.
        
        # Delegate confirmation state transitions to confirmation service
        confirmation_service = getattr(controller, "confirmation_service", None)
        if confirmation_service:
            await confirmation_service.handle_observation_for_pending_action(
                observation, ctx
            )
        else:
            await transition_agent_state_logic(controller, ctx, observation)

        self._trigger_post_resolution_step()

    @staticmethod
    def _matches_pending_action(pending_action, observation: Observation) -> bool:
        """Compare pending action id and observation cause robustly."""
        if pending_action is None:
            return False
        pending_id = getattr(pending_action, "id", None)
        cause = getattr(observation, "cause", None)
        if pending_id == cause:
            return True
        try:
            return pending_id is not None and cause is not None and int(pending_id) == int(cause)
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _report_pending_action_mismatch(
        controller: Any,
        *,
        pending_action,
        observation: Observation,
    ) -> None:
        pending_id = getattr(pending_action, "id", None) if pending_action else None
        message = (
            "Observation cause "
            f"{observation.cause!r} did not match pending action id {pending_id!r} "
            f"for {type(observation).__name__}"
        )
        logger.warning(message)
        controller.log("warning", message, extra={"msg_type": "OBSERVATION_MISMATCH"})

    async def _recover_from_pending_observation_mismatch(
        self,
        observation: Observation,
        pending_action,
    ) -> None:
        """Clear stale pending state and give the model explicit recovery guidance.

        Without this, a wrong ``cause`` id leaves pending set and the loop stalls
        even though the mismatched observation is already in history.
        """
        self._context.discard_invocation_context_for_action(pending_action)
        self._pending_service.set(None)
        pid = getattr(pending_action, "id", None)
        oc = getattr(observation, "cause", None)
        msg = (
            "The environment reported an observation that does not match the action "
            "the agent is waiting on. Pending action id was "
            f"{pid!r}; observation referred to {oc!r}. "
            "Treat any in-flight tool work as uncertain: verify the workspace before "
            "continuing, then choose a new approach if needed."
        )
        err = ErrorObservation(
            content=msg,
            error_id="OBSERVATION_PENDING_MISMATCH",
        )
        self._context.emit_event(err, EventSource.ENVIRONMENT)
        self._trigger_post_resolution_step()

    def _trigger_post_resolution_step(self) -> None:
        """Advance exactly once after a pending action is resolved in server mode."""
        self._context.trigger_step()

    def _prepare_observation_for_logging(self, observation: Observation) -> Observation:
        controller = self._context.get_controller()
        observation_to_print = copy.deepcopy(observation)
        max_chars = controller.agent.llm.config.max_message_chars
        if len(observation_to_print.content) > max_chars:
            observation_to_print.content = truncate_content(
                observation_to_print.content, max_chars
            )
        return observation_to_print

    def _get_log_level(self) -> str:
        return "info" if os.getenv("LOG_ALL_EVENTS") in ("true", "1") else "debug"
