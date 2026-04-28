from __future__ import annotations

import copy
import os
from typing import TYPE_CHECKING, Any

from backend.core.logger import app_logger as logger
from backend.ledger import EventSource
from backend.ledger.observation import ErrorObservation, Observation
from backend.ledger.serialization.event import truncate_content
from backend.orchestration.state.state import AgentState

# Background-only observation types that are allowed to arrive after pending
# has already advanced to the next action. Mismatches for these are silently
# dropped — not errors. Imported lazily in _is_background_observation to
# avoid circular imports at module load time.
_BACKGROUND_OBSERVATION_NAMES = frozenset(
    {'RecallObservation', 'RecallFailureObservation'}
)

if TYPE_CHECKING:
    from backend.orchestration.services.orchestration_context import (
        OrchestrationContext,
    )
    from backend.orchestration.services.pending_action_service import (
        PendingActionService,
    )
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

    pipeline = getattr(controller, 'tool_pipeline', None)
    if ctx and pipeline:
        await pipeline.run_observe(ctx, observation)
        if getattr(ctx, 'blocked', False) is True:
            controller.handle_blocked_invocation(ctx.action, ctx)
            return
        controller._cleanup_action_context(ctx)


class ObservationService:
    """Handles observation logging, metrics preparation, and pending-action observation flow."""

    def __init__(
        self,
        context: OrchestrationContext,
        pending_action_service: PendingActionService,
    ) -> None:
        self._context = context
        self._pending_service = pending_action_service

    async def handle_observation(self, observation: Observation) -> None:
        controller = self._context.get_controller()
        observation_to_print = self._prepare_observation_for_logging(observation)
        log_level = self._get_log_level()
        controller.log(
            log_level, str(observation_to_print), extra={'msg_type': 'OBSERVATION'}
        )
        await self._handle_pending_action_observation(observation)

    async def _handle_pending_action_observation(
        self, observation: Observation
    ) -> None:
        controller = self._context.get_controller()
        pending_action = await self._resolve_pending_action_for_observation(
            controller, observation
        )
        if pending_action is None:
            return

        # Plugin hook: action_post
        assert pending_action is not None  # _matches_pending_action requires this
        observation = await self._dispatch_action_post_hook(pending_action, observation)

        if controller.state.agent_state == AgentState.AWAITING_USER_CONFIRMATION:
            return

        await self._handle_resolved_pending_observation(
            controller, pending_action, observation
        )
        self._trigger_post_resolution_step()

    def _pending_action_from_cause(
        self, observation: Observation
    ) -> tuple[Any | None, bool]:
        cause = getattr(observation, 'cause', None)
        pending_action = self._pending_service.peek_for_cause(cause)
        if pending_action is not None:
            return pending_action, False
        if cause is None or not self._cause_coerces_to_stream_id(cause):
            return None, True
        if not self._pending_service.has_outstanding_for_cause(cause):
            logger.debug(
                'Dropping %s (cause=%r): no outstanding pending for that stream id '
                '(stale or duplicate observation)',
                type(observation).__name__,
                cause,
            )
            return None, False
        pending_action = self._pending_service.peek_for_cause(cause)
        if pending_action is not None:
            return pending_action, False
        logger.warning(
            'cause=%r is outstanding but peek_for_cause returned None; dropping %s',
            cause,
            type(observation).__name__,
        )
        return None, False

    async def _resolve_pending_action_for_observation(
        self, controller: Any, observation: Observation
    ) -> Any | None:
        pending_action, allow_primary_fallback = self._pending_action_from_cause(
            observation
        )
        if pending_action is not None or not allow_primary_fallback:
            return pending_action
        return await self._resolve_primary_pending_action(controller, observation)

    async def _resolve_primary_pending_action(
        self, controller: Any, observation: Observation
    ) -> Any | None:
        pending_action = self._pending_service.get()
        if pending_action is None:
            return None
        if self._matches_pending_action(pending_action, observation):
            return pending_action
        if getattr(observation, 'cause', None) is None:
            return None
        if self._is_background_observation(observation):
            logger.debug(
                'Silently dropping background observation %s (cause=%r) '
                'that arrived after pending advanced to id=%r',
                type(observation).__name__,
                getattr(observation, 'cause', None),
                getattr(pending_action, 'id', None),
            )
            return None
        self._report_pending_action_mismatch(
            controller,
            pending_action=pending_action,
            observation=observation,
        )
        await self._recover_from_pending_observation_mismatch(
            observation, pending_action
        )
        return None

    @staticmethod
    def _is_background_observation(observation: Observation) -> bool:
        return type(observation).__name__ in _BACKGROUND_OBSERVATION_NAMES

    async def _dispatch_action_post_hook(
        self, pending_action, observation: Observation
    ) -> Observation:
        try:
            from backend.core.plugin import get_plugin_registry

            return await get_plugin_registry().dispatch_action_post(
                pending_action, observation
            )
        except Exception as exc:
            logger.warning(
                'ObservationService action_post hook failed for %s: %s',
                type(pending_action).__name__,
                exc,
                exc_info=True,
            )
            return observation

    def _pop_action_context_for_observation(
        self, observation: Observation
    ) -> ToolInvocationContext | None:
        cause = getattr(observation, 'cause', None)
        if cause is None:
            return None
        return self._context.pop_action_context(cause)

    def _consume_pending_action(self, pending_action) -> None:
        aid = getattr(pending_action, 'id', None)
        if aid is not None:
            self._pending_service.pop_for_cause(aid)

    async def _handle_resolved_pending_observation(
        self,
        controller: Any,
        pending_action,
        observation: Observation,
    ) -> None:
        ctx = self._pop_action_context_for_observation(observation)
        self._consume_pending_action(pending_action)

        confirmation_service = getattr(controller, 'confirmation_service', None)
        if confirmation_service:
            await confirmation_service.handle_observation_for_pending_action(
                observation, ctx
            )
            return
        await transition_agent_state_logic(controller, ctx, observation)

    @staticmethod
    def _cause_coerces_to_stream_id(cause: object) -> bool:
        """True if *cause* parses like ``peek_for_cause`` / ``_outstanding`` keys."""
        try:
            int(cause)  # type: ignore[arg-type, call-overload]
        except (TypeError, ValueError):
            return False
        return True

    @staticmethod
    def _matches_pending_action(pending_action, observation: Observation) -> bool:
        """Compare pending action id and observation cause robustly."""
        if pending_action is None:
            return False
        pending_id = getattr(pending_action, 'id', None)
        cause = getattr(observation, 'cause', None)
        if pending_id == cause:
            return True
        try:
            return (
                pending_id is not None
                and cause is not None
                and int(pending_id) == int(cause)
            )
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _report_pending_action_mismatch(
        controller: Any,
        *,
        pending_action,
        observation: Observation,
    ) -> None:
        pending_id = getattr(pending_action, 'id', None) if pending_action else None
        message = (
            'Observation cause '
            f'{observation.cause!r} did not match pending action id {pending_id!r} '
            f'for {type(observation).__name__}'
        )
        logger.warning(message)
        controller.log('warning', message, extra={'msg_type': 'OBSERVATION_MISMATCH'})

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
        pid = getattr(pending_action, 'id', None)
        oc = getattr(observation, 'cause', None)
        msg = (
            'The environment reported an observation that does not match the action '
            'the agent is waiting on. Pending action id was '
            f'{pid!r}; observation referred to {oc!r}. '
            'Treat any in-flight tool work as uncertain: verify the workspace before '
            'continuing, then choose a new approach if needed.'
        )
        err = ErrorObservation(
            content=msg,
            error_id='OBSERVATION_PENDING_MISMATCH',
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
        return 'info' if os.getenv('LOG_ALL_EVENTS') in ('true', '1') else 'debug'
