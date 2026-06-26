from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import Mock

from backend.core.constants import LOG_ALL_EVENTS
from backend.ledger import EventSource
from backend.ledger.action import Action, ActionConfirmationStatus, NullAction
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
    # Agent MessageAction handoffs are protocol-validated by EventRouterService.
    return


def _bind_action_context_if_present(
    controller, action: Action, ctx: ToolInvocationContext | None
) -> None:
    if ctx is None:
        return
    ctx.action_id = action.id
    controller._bind_action_context(action, ctx)


def _install_one_shot_pending_hook(
    event_stream: EventStream,
    action_service: ActionService,
) -> object:
    previous_hook = event_stream.pre_runnable_action_dispatch

    def _arm_pending_before_dispatch(sanitized_action: Action) -> None:
        if callable(previous_hook):
            previous_hook(sanitized_action)
        action_service.set_pending_action(sanitized_action)

    event_stream.pre_runnable_action_dispatch = _arm_pending_before_dispatch
    return previous_hook


def _restore_pre_dispatch_hook(
    event_stream: EventStream, previous_hook: object
) -> None:
    event_stream.pre_runnable_action_dispatch = (
        previous_hook if callable(previous_hook) else None
    )


def _should_defer_stream_emission_until_confirmed(action: Action) -> bool:
    """Return True when the action must not be published to the event stream yet.

  Runnable actions that still need user approval are held back here and
  published once via :meth:`SessionOrchestrator.apply_user_decision`. Publishing
  them earlier made every subscriber (runtime, TUI, history) observe the same
  action twice — once while ``AWAITING_CONFIRMATION`` and again after approval —
  which duplicated shell/thinking rows in the transcript. File creates were
  especially confusing: the first pass wrote the file and showed ``Created``,
  then approval re-ran the action against the new file and showed ``Edited``.
    """
    if not getattr(action, 'runnable', False):
        return False
    return (
        getattr(action, 'confirmation_state', None)
        == ActionConfirmationStatus.AWAITING_CONFIRMATION
    )


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

        # Run pre-dispatch middleware before entering the user confirmation
        # gate. A blocked action must not leave AWAITING_USER_CONFIRMATION
        # without a pending action to confirm.
        if await _run_execute_pipeline_if_present(controller, action, ctx):
            return

        await self._confirmation_service.handle_pending_confirmation(action)

        self._prepare_metrics_for_action(action)

        try:
            from backend.orchestration.file_edits.file_edit_transaction import (
                get_file_edit_transaction_coordinator,
            )

            get_file_edit_transaction_coordinator(controller).before_action(action)
        except Exception:
            controller.log(
                'warning',
                'File edit transaction preflight failed; continuing without transaction guard.',
                extra={'msg_type': 'FILE_EDIT_TRANSACTION_PRECHECK_FAILED'},
            )

        # Lifecycle state for agent message handoffs is decided by the router
        # after protocol validation.
        await _set_waiting_message_state_if_needed(controller, action)

        if _should_defer_stream_emission_until_confirmed(action):
            self.set_pending_action(action)
            _bind_action_context_if_present(controller, action, ctx)
            log_level = 'info' if LOG_ALL_EVENTS else 'debug'
            controller.log(log_level, str(action), extra={'msg_type': 'ACTION'})
            return

        es = controller.event_stream
        previous_hook: object | None = None
        if action.runnable and isinstance(es, EventStream):
            lock = es.pre_dispatch_lock()
            async with lock:
                previous_hook = _install_one_shot_pending_hook(es, self)
                try:
                    controller.event_stream.add_event(
                        action, action.source or EventSource.AGENT
                    )
                finally:
                    _restore_pre_dispatch_hook(es, previous_hook)
        else:
            controller.event_stream.add_event(
                action, action.source or EventSource.AGENT
            )

        # MagicMock event streams do not run EventStream's pre-dispatch hook, so
        # keep tests and lightweight fakes on the old post-add path.
        if action.runnable and not isinstance(es, EventStream):
            self.set_pending_action(action)  # type: ignore[unreachable]

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
