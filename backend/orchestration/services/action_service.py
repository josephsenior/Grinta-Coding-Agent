from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import Mock

from backend.core.constants import LOG_ALL_EVENTS
from backend.core.schemas import AgentState
from backend.ledger import EventSource
from backend.ledger.action import Action, NullAction
from backend.ledger.action.message import MessageAction
from backend.ledger.stream import EventStream

if TYPE_CHECKING:
    from backend.orchestration.services.confirmation_service import ConfirmationService
    from backend.orchestration.services.orchestration_context import (
        OrchestrationContext,
    )
    from backend.orchestration.tool_pipeline import ToolInvocationContext


def _resolve_operation_pipeline(controller):
    controller_dict = getattr(controller, '__dict__', {})
    pipeline = controller_dict.get('operation_pipeline')
    if pipeline is None and not isinstance(controller, Mock):
        pipeline = getattr(controller, 'operation_pipeline', None)
    if pipeline is not None:
        return pipeline
    pipeline = controller_dict.get('tool_pipeline')
    if pipeline is not None:
        return pipeline
    return getattr(controller, 'tool_pipeline', None)


async def _run_execute_pipeline_if_present(
    controller,
    action: Action,
    ctx: ToolInvocationContext | None,
) -> bool:
    pipeline = _resolve_operation_pipeline(controller)
    if not ctx or not pipeline:
        return False
    await pipeline.run_execute(ctx)
    if not ctx.blocked:
        return False
    controller.handle_blocked_invocation(action, ctx)
    return True


async def _set_waiting_message_state_if_needed(controller, action: Action) -> None:
    if not isinstance(action, MessageAction):
        return
    if action.source != EventSource.AGENT or not action.wait_for_response:
        return
    await controller.set_agent_state_to(AgentState.AWAITING_USER_INPUT)


def _event_stream_has_pre_dispatch_hook(event_stream) -> bool:
    return (
        isinstance(event_stream, EventStream)
        and event_stream.pre_runnable_action_dispatch is not None
    )


def _bind_action_context_if_present(controller, action: Action, ctx: ToolInvocationContext | None) -> None:
    if ctx is None:
        return
    ctx.action_id = action.id
    controller._bind_action_context(action, ctx)


class ActionService:
    """Coordinates tool pipeline execute/observe and pending action lifecycle."""

    def __init__(
        self,
        context: OrchestrationContext,
        pending_action_service,
        confirmation_service: ConfirmationService,
    ) -> None:
        self._context = context
        self._pending_service = pending_action_service
        self._confirmation_service = confirmation_service

    async def run(self, action: Action, ctx: ToolInvocationContext | None) -> None:
        """Entry point used by SessionOrchestrator to process an action end-to-end."""
        if not isinstance(action, Action):
            raise TypeError('_process_action requires an Action instance')

        if action.runnable:
            await self._handle_runnable_action(action, ctx)

        controller = self._context.get_controller()
        if ctx and ctx.blocked:
            controller.handle_blocked_invocation(action, ctx)
            return

        if not isinstance(action, NullAction):
            await self._finalize_action(action, ctx)

    async def _handle_runnable_action(
        self, action: Action, ctx: ToolInvocationContext | None
    ) -> None:
        await self._confirmation_service.evaluate_action(action)

    async def _finalize_action(
        self, action: Action, ctx: ToolInvocationContext | None
    ) -> None:
        controller = self._context.get_controller()

        await self._confirmation_service.handle_pending_confirmation(action)
        if await _run_execute_pipeline_if_present(controller, action, ctx):
            return

        self._prepare_metrics_for_action(action)

        # Set AWAITING_USER_INPUT *before* emitting the event so that the
        # _step drain loop (which checks can_step → agent_state == RUNNING)
        # sees the state change immediately.  Without this, the event-stream
        # callback that normally sets AWAITING_USER_INPUT runs on a background
        # thread and may not execute before the drain loop re-enters
        # _step_inner, causing a duplicate LLM call and double response.
        await _set_waiting_message_state_if_needed(controller, action)

        es = controller.event_stream
        controller.event_stream.add_event(action, action.source or EventSource.AGENT)

        # When the real EventStream has no pre-dispatch hook, register pending
        # *after* add_event (so action.id is assigned). If
        # ``pre_runnable_action_dispatch`` is set, it already ran *inside* add_event
        # before inline delivery — avoids a race where the runtime observation
        # arrives before the pending map. Use ``isinstance(..., EventStream)`` so
        # unit tests with ``MagicMock`` event streams are not mis-detected as having
        # a hook (MagicMock attributes are truthy).
        if action.runnable and not _event_stream_has_pre_dispatch_hook(es):
            self.set_pending_action(action)

        _bind_action_context_if_present(controller, action, ctx)

        log_level = 'info' if LOG_ALL_EVENTS else 'debug'
        controller.log(log_level, str(action), extra={'msg_type': 'ACTION'})

    def _prepare_metrics_for_action(self, action: Action) -> None:
        """Attach cost/token metrics to an action before it's emitted."""
        controller = self._context.get_controller()
        metrics = controller.conversation_stats.get_combined_metrics()
        clean_metrics = metrics.copy()
        if controller.state.budget_flag:
            clean_metrics.max_budget_per_task = controller.state.budget_flag.max_value
        action.llm_metrics = clean_metrics

        latest_usage = None
        if controller.state.metrics.token_usages:
            latest_usage = controller.state.metrics.token_usages[-1]
        accumulated_usage = controller.state.metrics.accumulated_token_usage
        controller.log(
            'debug',
            f'Action metrics - accumulated_cost: {metrics.accumulated_cost}, '
            f'max_budget: {metrics.max_budget_per_task}, '
            f'latest tokens (prompt/completion/cache_read/cache_write): '
            f'{latest_usage.prompt_tokens if latest_usage else 0}/'
            f'{latest_usage.completion_tokens if latest_usage else 0}/'
            f'{latest_usage.cache_read_tokens if latest_usage else 0}/'
            f'{latest_usage.cache_write_tokens if latest_usage else 0}, '
            f'accumulated tokens (prompt/completion): '
            f'{accumulated_usage.prompt_tokens}/{accumulated_usage.completion_tokens}',
            extra={'msg_type': 'METRICS'},
        )

    def set_pending_action(self, action: Action | None) -> None:
        """Track pending action with timestamp; emit logging changes."""
        self._pending_service.set(action)

    def get_pending_action(self) -> Action | None:
        """Expose the pending action, auto-clearing when it times out."""
        return self._pending_service.get()

    def get_pending_action_info(self) -> tuple[Action, float] | None:
        return self._pending_service.info()
