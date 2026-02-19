from __future__ import annotations

import copy
import os
from typing import TYPE_CHECKING, Any

from backend.controller.state.state import AgentState
from backend.events.event import EventSource
from backend.events.observation import Observation
from backend.events.serialization.event import truncate_content

if TYPE_CHECKING:
    from backend.controller.services.controller_context import ControllerContext
    from backend.controller.services.pending_action_service import PendingActionService
    from backend.controller.state.context import ToolInvocationContext


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
        context: ControllerContext,
        pending_action_service: PendingActionService,
    ) -> None:
        self._context = context
        self._pending_service = pending_action_service
        self._action_verifier = None

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
        pending_action = self._pending_service.get()
        if not (pending_action and pending_action.id == observation.cause):
            return

        # Plugin hook: action_post
        try:
            from backend.core.plugin import get_plugin_registry

            observation = await get_plugin_registry().dispatch_action_post(
                pending_action, observation
            )
        except Exception:
            pass

        controller = self._context.get_controller()
        if controller.state.agent_state == AgentState.AWAITING_USER_CONFIRMATION:
            return

        ctx: ToolInvocationContext | None = None
        if observation.cause is not None:
            ctx = self._context.pop_action_context(observation.cause)

        self._pending_service.set(None)
        await self._run_post_action_verification(pending_action, observation)

        # Delegate confirmation state transitions to confirmation service
        confirmation_service = getattr(controller, "confirmation_service", None)
        if confirmation_service:
            await confirmation_service.handle_observation_for_pending_action(
                observation, ctx
            )
        else:
            await transition_agent_state_logic(controller, ctx, observation)

    async def _run_post_action_verification(
        self,
        action,
        observation: Observation,
    ) -> None:
        """Verify critical actions actually changed runtime state as expected."""
        from backend.events.observation import ErrorObservation

        if isinstance(observation, ErrorObservation):
            return

        verifier = self._get_action_verifier()
        if verifier is None:
            return

        if not verifier.should_verify(action):
            return

        controller = self._context.get_controller()
        try:
            ok, message, verification_observation = await verifier.verify_action(action)
        except Exception as exc:
            controller.log(
                "warning",
                f"Post-action verification crashed for {type(action).__name__}: {exc}",
                extra={"msg_type": "ACTION_VERIFICATION"},
            )
            return

        if verification_observation is not None:
            verification_observation.cause = None
            controller.event_stream.add_event(
                verification_observation,
                EventSource.ENVIRONMENT,
            )

        if ok:
            return

        controller.event_stream.add_event(
            ErrorObservation(
                content=(
                    "ACTION VERIFICATION FAILED:\n"
                    f"{message}\n"
                    "The agent should re-read the target file and re-apply the change."
                ),
                error_id="ACTION_VERIFICATION_FAILED",
            ),
            EventSource.ENVIRONMENT,
        )

    def _get_action_verifier(self):
        """Lazily construct ActionVerifier if runtime supports it."""
        if self._action_verifier is not None:
            return self._action_verifier

        controller = self._context.get_controller()
        runtime = getattr(controller, "runtime", None)
        if runtime is None:
            return None

        try:
            from backend.engines.orchestrator.action_verifier import ActionVerifier

            self._action_verifier = ActionVerifier(runtime)
        except Exception as exc:
            controller.log(
                "debug",
                f"ActionVerifier unavailable: {exc}",
                extra={"msg_type": "ACTION_VERIFICATION"},
            )
            self._action_verifier = None
        return self._action_verifier

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
