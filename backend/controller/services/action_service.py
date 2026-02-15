from __future__ import annotations

import copy
from typing import TYPE_CHECKING

from backend.core.constants import LOG_ALL_EVENTS
from backend.events import EventSource
from backend.events.action import Action, NullAction
from backend.llm.metrics import Metrics

if TYPE_CHECKING:
    from backend.controller.services.confirmation_service import ConfirmationService
    from backend.controller.services.controller_context import ControllerContext
    from backend.controller.tool_pipeline import ToolInvocationContext


class ActionService:
    """Coordinates tool pipeline verification/execute and pending action lifecycle."""

    def __init__(
        self,
        context: ControllerContext,
        pending_action_service,
        confirmation_service: ConfirmationService,
    ) -> None:
        self._context = context
        self._pending_service = pending_action_service
        self._confirmation_service = confirmation_service

    async def run(self, action: Action, ctx: ToolInvocationContext | None) -> None:
        """Entry point used by AgentController to process an action end-to-end."""
        if not isinstance(action, Action):
            raise TypeError("_process_action requires an Action instance")

        if action.runnable:
            await self._handle_runnable_action(action, ctx)

        controller = self._context.get_controller()
        if ctx and ctx.blocked:
            controller.telemetry_service.handle_blocked_invocation(action, ctx)
            return

        if not isinstance(action, NullAction):
            await self._finalize_action(action, ctx)

    async def _handle_runnable_action(
        self, action: Action, ctx: ToolInvocationContext | None
    ) -> None:
        controller = self._context.get_controller()
        pipeline = getattr(controller, "tool_pipeline", None)

        if ctx and pipeline:
            await pipeline.run_verify(ctx)
            if ctx.blocked:
                return

        await self._confirmation_service.evaluate_action(action)

        self.set_pending_action(action)

    async def _finalize_action(
        self, action: Action, ctx: ToolInvocationContext | None
    ) -> None:
        controller = self._context.get_controller()

        await self._confirmation_service.handle_pending_confirmation(action)

        pipeline = getattr(controller, "tool_pipeline", None)
        if ctx and pipeline:
            await pipeline.run_execute(ctx)
            if ctx.blocked:
                controller.telemetry_service.handle_blocked_invocation(action, ctx)
                return

        self._prepare_metrics_for_action(action)
        controller.event_stream.add_event(action, action.source or EventSource.AGENT)

        if ctx:
            ctx.action_id = action.id
            controller._bind_action_context(action, ctx)

        log_level = "info" if LOG_ALL_EVENTS else "debug"
        controller.log(log_level, str(action), extra={"msg_type": "ACTION"})

    def _prepare_metrics_for_action(self, action: Action) -> None:
        """Attach cost/token metrics to an action before it's emitted."""
        controller = self._context.get_controller()
        metrics = controller.conversation_stats.get_combined_metrics()

        clean_metrics = Metrics()
        clean_metrics.accumulated_cost = metrics.accumulated_cost
        clean_metrics._accumulated_token_usage = copy.deepcopy(
            metrics.accumulated_token_usage
        )
        if controller.state.budget_flag:
            clean_metrics.max_budget_per_task = controller.state.budget_flag.max_value
        action.llm_metrics = clean_metrics

        latest_usage = None
        if controller.state.metrics.token_usages:
            latest_usage = controller.state.metrics.token_usages[-1]
        accumulated_usage = controller.state.metrics.accumulated_token_usage
        controller.log(
            "debug",
            f"Action metrics - accumulated_cost: {metrics.accumulated_cost}, "
            f"max_budget: {metrics.max_budget_per_task}, "
            f"latest tokens (prompt/completion/cache_read/cache_write): "
            f"{latest_usage.prompt_tokens if latest_usage else 0}/"
            f"{latest_usage.completion_tokens if latest_usage else 0}/"
            f"{latest_usage.cache_read_tokens if latest_usage else 0}/"
            f"{latest_usage.cache_write_tokens if latest_usage else 0}, "
            f"accumulated tokens (prompt/completion): "
            f"{accumulated_usage.prompt_tokens}/{accumulated_usage.completion_tokens}",
            extra={"msg_type": "METRICS"},
        )

    def set_pending_action(self, action: Action | None) -> None:
        """Track pending action with timestamp; emit logging changes."""
        self._pending_service.set(action)

    def get_pending_action(self) -> Action | None:
        """Expose the pending action, auto-clearing when it times out."""
        return self._pending_service.get()

    def get_pending_action_info(self) -> tuple[Action, float] | None:
        return self._pending_service.info()
