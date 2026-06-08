from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any, cast

from backend.core.logger import app_logger as logger
from backend.core.schemas import AgentState
from backend.ledger.action import (
    Action,
)
from backend.utils.async_utils import (
    run_or_schedule,
)

TRAFFIC_CONTROL_REMINDER = (
    "Please click on resume button if you'd like to continue, or start a new task."
)
ERROR_ACTION_NOT_EXECUTED_STOPPED_ID = 'AGENT_ERROR$ERROR_ACTION_NOT_EXECUTED_STOPPED'
ERROR_ACTION_NOT_EXECUTED_ERROR_ID = 'AGENT_ERROR$ERROR_ACTION_NOT_EXECUTED_ERROR'
ERROR_ACTION_NOT_EXECUTED_STOPPED = 'Run cancelled (Stop or Ctrl+C) before this tool finished — the action was not executed.'
ERROR_ACTION_NOT_EXECUTED_ERROR = (
    'Runtime error or restart prevented this action from completing (unlike cancelling with '
    'Stop or Ctrl+C). The execution environment may have crashed or been recycled. '
    'Any previously established system state, dependencies, or environment variables '
    'may have been lost. Consider using /resume to restore a crashed session.'
)

PARALLEL_TOOL_BATCH_RETRIES = 1
PARALLEL_TOOL_BATCH_BACKOFF_SECONDS = 0.25


def _mark_retry_serial_after_parallel_failure(action: Action) -> None:
    cast(Any, action)._retry_serial_after_parallel_failure = True


def _invoke_zero_arg_callback(callback: Callable[[], object]) -> object:
    return callback()


if TYPE_CHECKING:
    from backend.core.enums import AgentState
    from backend.ledger.event import Event
    from backend.utils.async_utils import (
        run_or_schedule,
    )

"""_SessionOrchestratorStepMixin mixin for SessionOrchestrator.

Pure code motion: extracted from
``backend/orchestration/session_orchestrator.py`` to break the file past the
40 KB cap. Methods here are bound to ``_SessionOrchestratorStepMixin`` and mixed into
``SessionOrchestrator`` via its MRO.
"""


class _SessionOrchestratorStepMixin:
    """Mixin: step scheduling, exception handling, event dispatch, reset."""

    def schedule_step_soon(self) -> None:
        """Schedule a step.

        Alias for :meth:`SessionOrchestrator.step`, which already funnels
        through ``call_soon_threadsafe`` to the main loop and atomically
        sets ``_step_request`` (or creates a task) inside
        ``_request_step``.  Kept for backward compatibility with callers
        that historically used this entry point.
        """
        self.step()

    def _create_step_task(self) -> None:
        """Create the step task.  Must be called on the main event loop.

        The caller (``_request_step`` or ``_step``'s teardown callback) is
        the only one that schedules us, and it has already verified that
        ``_step_task`` is None or done before calling.  This method just
        resets the request event and creates a fresh task.
        """
        from backend.utils.async_utils import create_tracked_task

        self._step_request_count = 0
        self._step_task = create_tracked_task(
            self._step_with_exception_handling(),
            name='agent-step',
        )

    async def _step_with_exception_handling(self) -> None:
        """Execute agent step with comprehensive exception handling."""
        try:
            await self._step()

        except Exception as e:
            # P1-STAB: If the agent was stopped (e.g. via interrupt/ctrl+c) and the runtime

            # was killed while this step was waiting for the LLM, a DisconnectedError

            # is expected. Swallow it to avoid noisy error popups for the user.

            from backend.core.errors import AgentRuntimeDisconnectedError

            if self.get_agent_state() == AgentState.STOPPED and isinstance(
                e, AgentRuntimeDisconnectedError
            ):
                logger.info('Ignoring runtime disconnection error after agent stop.')

                return

            # CancelledError (BaseException) propagates; only handle Exception

            await self.exception_handler.handle_step_exception(e)

    def should_step(self, event: Event) -> bool:
        """Whether the agent should take a step based on an event."""
        return self.step_decision.should_step(event)

    @property
    def _step_lock(self) -> asyncio.Lock:
        """Lazily initialize the lock on the current event loop."""
        current_loop = None

        with contextlib.suppress(RuntimeError):
            current_loop = asyncio.get_running_loop()

        if self._step_lock_instance is None or (
            current_loop is not None
            and self._step_lock_loop is not None
            and current_loop is not self._step_lock_loop
        ):
            self._step_lock_instance = asyncio.Lock()

            self._step_lock_loop = current_loop

        return self._step_lock_instance

    async def reset_controller(self) -> None:
        owner = self._step_owner_task

        if owner is not None and asyncio.current_task() is owner:
            self._reset()

            return

        async with self._step_lock:
            self._reset()

    async def _react_to_exception(self, e: Exception) -> None:
        """Delegate exception handling to the recovery service."""
        await self.services.recovery.react_to_exception(e)

    def on_event(self, event: Event) -> None:
        """Callback from the event stream. Notifies the controller of incoming events."""
        if self._closed:
            return

        run_or_schedule(self._on_event(event))

    async def _on_event(self, event: Event) -> None:
        """Handle incoming events from the event stream."""
        if self._closed:
            return

        try:
            await self.event_router.route_event(event)

            # Drive the agent loop forward for events that should trigger a step.

            # This is necessary in the server (event-driven) path because there is

            # no external polling loop like run_agent_until_done in CLI/headless mode.

            # Examples: ThinkObservation, most tool observations (after pending is

            # cleared by observation_service.trigger_step), etc.

            # ``step()`` is now race-free: it dispatches ``_request_step`` onto
            # the main loop, which atomically sets ``_step_request`` (if a task
            # is alive) or creates a new task.  No deferral indirection is
            # needed.
            if not self._closed and self.should_step(event):
                self.step()
        except Exception as exc:
            event_type = type(event).__name__
            event_id = getattr(event, 'id', '?')
            logger.error(
                '_on_event: unhandled exception processing %s (id=%s): %s: %s',
                event_type,
                event_id,
                type(exc).__name__,
                exc,
                exc_info=True,
                extra={'msg_type': 'ON_EVENT_EXCEPTION'},
            )
            if not self._closed and self.should_step(event):
                try:
                    self.step()
                except Exception:
                    pass

    def _schedule_coroutine(self, coro: Coroutine[Any, Any, Any]) -> None:
        """Schedule a coroutine using the current or new event loop."""
        run_or_schedule(coro)

    def _reset(self) -> None:
        """Resets the agent controller.

        Must be called only from within the step lock to prevent concurrent mutation

        of action contexts and agent state during an active step.

        """
        self._clear_action_contexts()

        self._emit_pending_action_error_if_unmatched()

        self._emit_dropped_agent_actions()

        pending_service = getattr(
            getattr(self, 'services', None), 'pending_action', None
        )
        if pending_service is not None:
            pending_service.clear_all()

        agent = getattr(self, 'agent', None)

        if agent is not None:
            agent.reset()

    def _clear_action_contexts(self) -> None:
        """Clear action context caches."""
        if hasattr(self, '_action_contexts_by_object'):
            self._action_contexts_by_object.clear()

        if hasattr(self, '_action_contexts_by_event_id'):
            self._action_contexts_by_event_id.clear()

    def mark_user_interrupt_stop(self) -> None:
        """Next `_reset` should not emit unmatched-pending ErrorObservation (REPL Ctrl+C)."""
        self._suppress_pending_unmatched_error_on_reset = True
