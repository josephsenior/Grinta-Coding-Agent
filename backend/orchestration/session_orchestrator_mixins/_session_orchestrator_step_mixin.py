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
    get_main_event_loop,
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
        get_main_event_loop,
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
        """Schedule a fresh ``step()`` on the main loop after the current turn unwinds.

        Unlike calling ``step()`` inline from within an active step task, this

        defers re-entry until the event loop regains control. That avoids the

        race where ``step()`` only flips ``_step_pending`` while the current

        task is still running and the flag is then cleared during ``_step()``

        shutdown.

        """
        if self._closed:
            return

        # Record that a step is being scheduled.  The no-step-progress
        # watchdog reads this to know that the agent is not genuinely stuck
        # — a slow LLM streaming response is expected to take longer than
        # the watchdog timeout, but as long as step() keeps getting called
        # the watchdog stays quiet.
        cb = getattr(self, 'circuit_breaker', None) or getattr(
            self, '_circuit_breaker', None
        )
        if cb is not None and hasattr(cb, 'record_step_call'):
            try:
                cb.record_step_call()
            except Exception:
                pass

        main_loop = get_main_event_loop()

        if main_loop is not None and main_loop.is_running():
            main_loop.call_soon_threadsafe(self.step)

            return

        with contextlib.suppress(RuntimeError):
            asyncio.get_running_loop().call_soon(self.step)

            return

        self.step()

    def _create_step_task(self) -> None:
        """Create the step task on the current (main) running loop.

        This method must only be called while holding _step_gate, either

        directly from step() or via call_soon_threadsafe on the main loop.

        The caller's gate acquisition prevents the race window.

        """
        # Fast path: task still running — re-queue pending and exit.

        # This check is safe because the gate was held at the call site;

        # a second concurrent _create_step_task from another thread would

        # have been blocked at step().

        if self._step_task and not self._step_task.done():
            # Mirror the counter bump in step() so the in-flight _step
            # task's finally block knows NOT to clobber _step_pending.
            self._step_seq += 1
            self._step_pending = True

            return

        from backend.utils.async_utils import create_tracked_task

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

        await self.event_router.route_event(event)

        # Drive the agent loop forward for events that should trigger a step.

        # This is necessary in the server (event-driven) path because there is

        # no external polling loop like run_agent_until_done in CLI/headless mode.

        # Examples: ThinkObservation, most tool observations (after pending is

        # cleared by observation_service.trigger_step), etc.

        # IMPORTANT: must funnel through ``schedule_step_soon`` (not a direct
        # ``self.step()``) to dodge the race documented in
        # :meth:`schedule_step_soon`.  A direct call here races with the
        # in-flight ``_step`` task's ``finally`` block: the call sees the
        # previous ``_step_task`` as still alive, sets ``_step_pending = True``,
        # returns — and the just-finishing ``_step`` task immediately clears
        # ``_step_pending`` in its teardown, leaving the agent with no
        # re-queued step and visibly stuck in ``AgentState.RUNNING`` forever.
        if not self._closed and self.should_step(event):
            self.schedule_step_soon()

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

        self._pending_action = None

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
