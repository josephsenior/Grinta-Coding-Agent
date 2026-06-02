from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

from backend.core.logger import app_logger as logger
from backend.core.schemas import AgentState
from backend.ledger import EventSource
from backend.ledger.action import (
    Action,
)
from backend.ledger.observation import (
    ErrorObservation,
    Observation,
)
from backend.ledger.observation_cause import attach_observation_cause

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
    from backend.ledger.action import Action
    from backend.ledger.event import EventSource
    from backend.ledger.observation import (
        ErrorObservation,
        Observation,
    )

"""_SessionOrchestratorParallelMixin mixin for SessionOrchestrator.

Pure code motion: extracted from
``backend/orchestration/session_orchestrator.py`` to break the file past the
40 KB cap. Methods here are bound to ``_SessionOrchestratorParallelMixin`` and mixed into
``SessionOrchestrator`` via its MRO.
"""


class _SessionOrchestratorParallelMixin:
    """Mixin: parallel read batch, post-execution, pending action drain."""

    async def _try_parallel_read_batch(self) -> bool:
        """Attempt to drain pending actions in parallel when scheduler allows.

        P2-B: When the LLM emits multiple read-only actions, execute the selected

        batch concurrently via asyncio.gather instead of sequentially.



        The PendingActionService already tracks multiple outstanding actions by

        stream ID (dict[int, tuple[Action, float]]), so concurrent execute_action

        calls safely register independent pending entries that get resolved by

        their matching observations.



        Returns True if batch was executed (caller should skip the serial drain),

        False when parallel scheduling is disabled or unsafe for the current queue.

        """
        pending = getattr(self.agent, 'pending_actions', None)

        if not pending:
            return False

        if any(
            getattr(action, '_retry_serial_after_parallel_failure', False)
            for action in pending
        ):
            return False

        scheduler = getattr(self, 'action_scheduler', None)

        if scheduler is None:
            return False

        decision = scheduler.decide_parallel_batch(list(pending))

        if not decision.should_execute_parallel:
            return False

        batch = list(decision.actions)

        if not batch:
            return False

        def _detach_parallel_batch(queue: object, expected: list[Action]) -> bool:
            if not expected:
                return True

            popleft = getattr(queue, 'popleft', None)

            if callable(popleft):
                for exp in expected:
                    try:
                        got = popleft()

                    except Exception:
                        return False

                    if got is not exp:
                        appendleft = getattr(queue, 'appendleft', None)

                        if callable(appendleft):
                            appendleft(got)

                        return False

                return True

            if isinstance(queue, list):
                if len(queue) < len(expected):
                    return False

                if any(queue[i] is not expected[i] for i in range(len(expected))):
                    return False

                del queue[: len(expected)]

                return True

            return False

        if not _detach_parallel_batch(pending, batch):
            return False

        logger.debug(
            '[scheduler] Parallel tool batch: executing %d actions (%s, %d overflow deferred)',
            len(batch),
            decision.reason,
            len(decision.overflow),
        )

        def _prepend_action(queue: object, action: Action) -> None:
            appendleft = getattr(queue, 'appendleft', None)

            if callable(appendleft):
                appendleft(action)

                return

            insert = getattr(queue, 'insert', None)

            if callable(insert):
                insert(0, action)

        to_run = list(batch)

        attempt = 0

        failed_actions: list[Action] = []

        last_failures: list[BaseException] = []

        while True:
            results = await asyncio.gather(
                *(self.action_execution.execute_action(a) for a in to_run),
                return_exceptions=True,
            )

            failed_actions = []

            last_failures = []

            for i, result in enumerate(results):
                if isinstance(result, BaseException):
                    if isinstance(
                        result, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)
                    ):
                        raise result

                    failed_action = to_run[i]

                    failed_actions.append(failed_action)

                    last_failures.append(result)

                    action_type = getattr(
                        failed_action, 'action', type(failed_action).__name__
                    )

                    logger.warning(
                        '[P2-B] Parallel batch action %d (%s) failed: %s',
                        i,
                        action_type,
                        result,
                    )

            if not failed_actions or attempt >= PARALLEL_TOOL_BATCH_RETRIES:
                break

            await asyncio.sleep(PARALLEL_TOOL_BATCH_BACKOFF_SECONDS * (2**attempt))

            to_run = list(failed_actions)

            attempt += 1

        # Mark only FAILED actions for serial retry. Successful actions must NOT

        # be marked — once they succeed on retry, the flag would cause them to be

        # returned serially on every subsequent get_next_action() call even though

        # they already succeeded, creating an infinite re-execution loop.

        for failed_action in failed_actions:
            _mark_retry_serial_after_parallel_failure(failed_action)

        if failed_actions:
            for failure in last_failures:
                try:
                    if isinstance(failure, Exception):
                        await self._react_to_exception(failure)

                    else:
                        await self._react_to_exception(RuntimeError(str(failure)))

                except Exception:
                    logger.debug(
                        'Failed to react to parallel batch exception', exc_info=True
                    )

            current_pending = getattr(self.agent, 'pending_actions', None)

            if current_pending is not None:
                for action in reversed(failed_actions):
                    _prepend_action(current_pending, action)

        await self._handle_post_execution()

        return True

    def _can_drain_pending(self) -> bool:
        """Check if we can immediately execute the next queued action.

        Returns True when no action is awaiting its observation (i.e. the last

        action was non-runnable) AND the agent has more queued actions from the

        same LLM response.

        """
        if self._pending_action:
            return False

        pending = getattr(self.agent, 'pending_actions', None)

        return bool(pending)

    async def _handle_post_execution(self) -> None:
        """Handle post-execution tasks like rate limits and memory pressure."""
        # Memory-pressure → rate-governor feedback loop

        ratio = self.memory_pressure.pressure_ratio()

        factor = 1.0 - (ratio * 0.75)

        self.rate_governor.set_memory_pressure_factor(factor)

        # Check rate limits after action execution (which likely consumed tokens)

        if hasattr(self.state, 'metrics'):
            await self.rate_governor.check_and_wait(
                self.state.metrics.accumulated_token_usage
            )

        # Feed LLM latency for adaptive backoff

        llm_lat = getattr(self.agent, '_last_llm_latency', None)

        if llm_lat and llm_lat > 0:
            self.rate_governor.record_llm_latency(llm_lat)

        # Proactive condensation on memory pressure (deferred during batch drain)

        history = getattr(self.state, 'history', None)

        history_events = len(history) if history is not None else None

        if not self._draining_batch and self.memory_pressure.should_condense(
            history_events=history_events
        ):
            level = 'CRITICAL' if self.memory_pressure.is_critical() else 'WARNING'

            if (
                level == 'WARNING'
                and not self.memory_pressure.is_prewarming
                and not self.memory_pressure.has_prewarmed
            ):
                # Phase 3.11: Opportunistically pre-warm condensation in the background.

                # Creates an isolated copy of state/history so the foreground agent

                # can keep mutating the real state.

                mm = getattr(self.agent, 'memory_manager', None)

                if mm is not None and getattr(mm, 'compactor', None) is not None:
                    import asyncio
                    from copy import copy

                    compactor = mm.compactor

                    state_copy = copy(self.state)

                    state_copy.history = list(history) if history else []

                    async def _run_bg():
                        return await compactor.compacted_history(state_copy)

                    self.memory_pressure.start_prewarm(_run_bg)

                    logger.debug('Kicked off background condensation pre-warm')

            logger.warning(
                'Memory pressure %s (RSS=%.0f MB) — signalling condensation',
                level,
                self.memory_pressure._last_rss_mb,
            )

            # Only record sync blocks as full condensations (Phase 3.14).

            if (
                level == 'CRITICAL'
                and not self.memory_pressure.has_prewarmed
                and not self.memory_pressure.is_prewarming
            ):
                self.memory_pressure.record_condensation()

            # Set a metadata flag the orchestrator can check during next step()

            if hasattr(self.state, 'turn_signals'):
                # Wait for any active prewarm to finish if we hit critical

                if level == 'CRITICAL' and self.memory_pressure.is_prewarming:
                    logger.debug(
                        'Critical memory pressure: awaiting in-flight prewarm task...'
                    )

                    import asyncio

                    # Notify the TUI that compaction is blocking execution

                    try:
                        from backend.ledger import EventSource
                        from backend.ledger.observation import StatusObservation

                        compaction_status = StatusObservation(
                            content='Compacting context...',
                            status_type='compaction',
                        )

                        self.event_stream.add_event(
                            compaction_status, EventSource.AGENT
                        )

                    except Exception:
                        pass  # Never let UI notification crash the compaction path

                    try:
                        if self.memory_pressure._prewarm_task:
                            await asyncio.shield(self.memory_pressure._prewarm_task)

                    except Exception as e:
                        logger.warning(
                            'Prewarm task failed during critical await: %s', e
                        )

                self.state.set_memory_pressure(level, source='SessionOrchestrator')

                if level == 'CRITICAL':
                    if self.memory_pressure.has_prewarmed:
                        prewarmed = self.memory_pressure.consume_prewarmed()

                        self.state.turn_signals.prewarmed_compaction = prewarmed

                        logger.info('Injected prewarmed compaction into turn signals.')

                    else:
                        self.state.turn_signals.prewarmed_compaction = None

    async def _run_control_flags_safely(self) -> bool:
        """Run control flags with exception handling."""
        try:
            await self.iteration_guard.run_control_flags()

            return True

        except Exception as e:
            await self._react_to_exception(e)

            return False

    def _emit_pending_action_error_if_unmatched(self) -> None:
        """Emit ErrorObservation if pending action has no matching observation."""
        if getattr(self, '_suppress_pending_unmatched_error_on_reset', False):
            self._suppress_pending_unmatched_error_on_reset = False

            return

        if not self._pending_action or not hasattr(
            self._pending_action, 'tool_call_metadata'
        ):
            return

        meta = self._pending_action.tool_call_metadata

        found = any(
            isinstance(e, Observation) and e.tool_call_metadata == meta
            for e in self.state.history
        )

        if found:
            return

        content, err_id = (
            (ERROR_ACTION_NOT_EXECUTED_STOPPED, ERROR_ACTION_NOT_EXECUTED_STOPPED_ID)
            if self.state.agent_state == AgentState.STOPPED
            else (ERROR_ACTION_NOT_EXECUTED_ERROR, ERROR_ACTION_NOT_EXECUTED_ERROR_ID)
        )

        obs = ErrorObservation(content=content, error_id=err_id)

        obs.tool_call_metadata = meta

        attach_observation_cause(
            obs, self._pending_action, context='agent_controller.pending_unmatched'
        )

        self.event_stream.add_event(obs, EventSource.AGENT)

    def _emit_dropped_agent_actions(self) -> None:
        """Emit ErrorObservations for agent-queued actions dropped by reset."""
        iter_queued = getattr(self.agent, 'iter_queued_actions', None)

        if callable(iter_queued):
            dropped_actions = list(iter_queued())

        else:
            agent_pending = getattr(self.agent, 'pending_actions', None)

            dropped_actions = list(agent_pending or [])

        if not dropped_actions:
            return

        for dropped in dropped_actions:
            meta = getattr(dropped, 'tool_call_metadata', None)

            if not meta:
                continue

            obs = ErrorObservation(
                content=(
                    'Action dropped: agent was reset before this tool call '
                    'could execute. Re-run this action if still needed.'
                ),
                error_id=ERROR_ACTION_NOT_EXECUTED_ERROR_ID,
            )

            obs.tool_call_metadata = meta

            attach_observation_cause(
                obs, dropped, context='agent_controller.dropped_action'
            )

            self.event_stream.add_event(obs, EventSource.AGENT)

    @property
    def _pending_action(self) -> Action | None:
        pending_service = self.services.pending_action

        if pending_service:
            return pending_service.get()

        return None

    @_pending_action.setter
    def _pending_action(self, action: Action | None) -> None:
        pending_service = self.services.pending_action

        if pending_service:
            pending_service.set(action)
