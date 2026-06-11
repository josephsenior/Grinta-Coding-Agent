"""Agent controller orchestration, logging, and execution helpers."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

from backend.utils.async_utils import (
    get_main_event_loop,
    set_main_event_loop,
)

if TYPE_CHECKING:
    from backend.core.config import AgentConfig, LLMConfig
    from backend.orchestration.replay import ReplayManager
    from backend.orchestration.state.state_tracker import StateTracker
    from backend.persistence.files import FileStore
    from backend.security.analyzer import SecurityAnalyzer

from backend.core.constants import (
    DEFAULT_AGENT_STEP_DRAIN_LIMIT,
    DEFAULT_PENDING_ACTION_TIMEOUT,
)
from backend.core.enums import LifecyclePhase
from backend.core.logger import app_logger as logger
from backend.core.schemas import AgentState
from backend.core.step_phase import clear_step_phase, set_step_phase
from backend.ledger import EventSource, EventStreamSubscriber
from backend.ledger.action import (
    Action,
    MessageAction,
)
from backend.orchestration.action_scheduler import ActionScheduler
from backend.orchestration.memory_pressure import MemoryPressureMonitor
from backend.orchestration.orchestration_config import (
    OrchestrationConfig,
    OrchestrationServices,
)
from backend.orchestration.rate_governor import LLMRateGovernor
from backend.orchestration.session_orchestrator_accessors import (
    SessionOrchestratorAccessorsMixin,
)
from backend.orchestration.session_orchestrator_mixins._session_orchestrator_action_mixin import (
    _SessionOrchestratorActionMixin,
)
from backend.orchestration.session_orchestrator_mixins._session_orchestrator_lifecycle_mixin import (
    _SessionOrchestratorLifecycleMixin,
)
from backend.orchestration.session_orchestrator_mixins._session_orchestrator_parallel_mixin import (
    _SessionOrchestratorParallelMixin,
)
from backend.orchestration.session_orchestrator_mixins._session_orchestrator_state_mixin import (
    _SessionOrchestratorStateMixin,
)
from backend.orchestration.session_orchestrator_mixins._session_orchestrator_step_mixin import (
    _SessionOrchestratorStepMixin,
)
from backend.orchestration.tool_pipeline import ToolInvocationContext

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


class SessionOrchestrator(
    SessionOrchestratorAccessorsMixin,
    _SessionOrchestratorStepMixin,
    _SessionOrchestratorLifecycleMixin,
    _SessionOrchestratorParallelMixin,
    _SessionOrchestratorStateMixin,
    _SessionOrchestratorActionMixin,
):
    """Main orchestrator class. 6 core methods live here; 46 in mixins."""

    """Coordinates agent loop execution, event stream handling, and runtime interactions."""
    config: OrchestrationConfig
    services: OrchestrationServices
    _lifecycle_phase: LifecyclePhase = LifecyclePhase.INITIALIZING
    _cached_first_user_message: MessageAction | None = None
    state_tracker: StateTracker
    _replay_manager: ReplayManager
    PENDING_ACTION_TIMEOUT: float = DEFAULT_PENDING_ACTION_TIMEOUT
    _step_task: asyncio.Task[None] | None = None
    # Counter incremented by ``_request_step`` to request another step iteration.
    # ``_step``'s drain loop decrements it.  All mutations happen on the main
    # event loop, so the counter is implicitly thread-safe via the
    # call_soon_threadsafe funnel.  Using an integer counter instead of an
    # asyncio.Event eliminates the lost-wakeup race where the finally block
    # clears the event between an external set() and the scheduled
    # _create_step_task.
    _step_request_count: int = 0
    rate_governor: LLMRateGovernor
    memory_pressure: MemoryPressureMonitor
    action_scheduler: ActionScheduler
    _action_contexts_by_event_id: dict[int, ToolInvocationContext]
    _action_contexts_by_object: dict[int, ToolInvocationContext]
    user_id: str | None
    file_store: FileStore | None
    headless_mode: bool
    status_callback: Callable | None
    security_analyzer: SecurityAnalyzer | None
    agent_to_llm_config: dict[str, LLMConfig]
    agent_configs: dict[str, AgentConfig]
    _initial_max_iterations: int
    _initial_max_budget_per_task: float | None
    autonomy_controller: Any
    safety_validator: Any
    task_validator: Any
    runtime: Any
    tool_pipeline: Any
    _lifecycle: LifecyclePhase

    def __init__(self, config: OrchestrationConfig) -> None:
        """Initializes a new instance of the SessionOrchestrator class."""
        self.config = config

        # The main event loop is resolved dynamically in step() via
        # get_main_event_loop() so we never capture a throw-away worker
        # loop during thread-pool construction or session resume.
        # We only prime the global registry here when we happen to be on
        # the real main loop during normal construction.
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None:
            set_main_event_loop(loop)

        # Attributes set by telemetry service during pipeline initialization
        self._reflection_middleware_enabled: bool = False
        self._file_state_tracker: Any = None

        # --- Service wiring (order matters) ---
        self.PENDING_ACTION_TIMEOUT = config.pending_action_timeout
        self.services = OrchestrationServices(self)

        # Rate governor and memory monitor
        self.rate_governor = LLMRateGovernor()
        self.memory_pressure = MemoryPressureMonitor()
        self.action_scheduler = ActionScheduler(
            enabled=bool(getattr(config, 'enable_parallel_tool_scheduling', False))
        )

        # Guard against concurrent step execution across dispatch threads.
        # Initialized lazily to ensure correct event loop binding.
        self._step_lock_instance: asyncio.Lock | None = None
        self._step_lock_loop: asyncio.AbstractEventLoop | None = None
        self._step_owner_task: asyncio.Task[Any] | None = None
        # Step request counter.  ``_request_step`` increments when a step is
        # requested while a step task is in-flight; ``_step``'s drain loop
        # decrements.  All mutations happen on the main event loop, so the
        # counter is implicitly thread-safe via the call_soon_threadsafe funnel.
        # Using an integer counter instead of an asyncio.Event eliminates the
        # lost-wakeup race where the finally block clears the event between
        # an external set() and the scheduled _create_step_task.
        self._step_request_count = 0
        # Suppresses memory-pressure condensation signalling during batch drain
        # so that pending actions are not disrupted mid-batch.
        self._draining_batch = False
        # CLI Ctrl+C: skip pending-unmatched ErrorObservation on next _reset().
        self._suppress_pending_unmatched_error_on_reset: bool = False

        # Independent watchdog timer for stall detection.
        # This runs as a standalone background task, not inside _step_inner(),
        # so it can detect stalls even when the step loop stops running entirely.
        self._watchdog_task: asyncio.Task[None] | None = None
        self._watchdog_last_step_ts: float = 0.0
        self._watchdog_auto_recover_ts: float = 0.0

        # Initialize core state via lifecycle service
        self._initialize_operation_pipeline()
        self.services.lifecycle.initialize_core_attributes(
            config.sid,
            config.event_stream,
            config.agent,
            config.user_id,
            config.file_store,
            config.headless_mode,
            config.conversation_stats,
            config.status_callback,
            config.security_analyzer,
        )

        self.services.lifecycle.initialize_state_and_tracking(
            config.sid,
            config.file_store,
            config.user_id,
            config.initial_state,
            config.conversation_stats,
            config.iteration_delta,
            config.budget_per_task_delta,
            config.replay_events,
        )

        self.services.stuck.initialize(self.state)
        self.services.lifecycle.initialize_agent_configs(
            config.agent_to_llm_config,
            config.agent_configs,
            config.iteration_delta,
            config.budget_per_task_delta,
        )
        self.services.autonomy.initialize(config.agent)
        self.services.retry.initialize()

        # C-P1-1: snapshot post-init state so users can rewind to a "fresh
        # session" baseline. Now that the pipeline is initialized, the
        # rollback middleware will correctly capture the checkpoint.
        self._create_phase_boundary_checkpoint('init_to_active')

    def step(self) -> None:
        """Trigger agent to take one step asynchronously.

        Creates an async task for step execution if one is not already running.
        Otherwise, marks the current step as pending to re-trigger after completion.
        Maintains a strong reference to the task to prevent garbage collection.

        The task is always scheduled on the main event loop (captured during
        __init__) because this method is often called from EventStream's
        thread-pool dispatcher which runs disposable event loops.

        Thread-safe: dispatches ``_request_step`` onto the main loop via
        ``call_soon_threadsafe`` (or runs it inline if the main loop is
        unavailable).  The check-and-set of ``_step_request`` /
        ``_step_task`` happens inside ``_request_step`` on the main loop,
        so the operation is atomic without any additional threading lock.
        """
        if self._closed:
            return

        # Record that a step was requested — the no-step-progress watchdog
        # uses this to detect a controller that's stuck in RUNNING with no
        # one calling step().  Failure to record here is non-fatal: the
        # watchdog is a safety net, not a primary control.
        cb = getattr(self, 'circuit_breaker', None) or getattr(
            self, '_circuit_breaker', None
        )
        if cb is not None and hasattr(cb, 'record_step_call'):
            try:
                cb.record_step_call()
            except Exception:
                pass
        self._record_watchdog_step()

        main_loop = get_main_event_loop()
        if main_loop is not None and main_loop.is_running():
            main_loop.call_soon_threadsafe(self._request_step)
        else:
            self._request_step()

    def _request_step(self) -> None:
        """Run on the main event loop.  Atomically routes a step request.

        If a step task is already running, set ``_step_request`` so the
        in-flight drain loop picks up another iteration.  Otherwise create
        a fresh step task.  Replaces the previous ``_step_gate`` lock that
        serialised the check-and-create across threads.
        """
        if self._closed:
            return
        if self._step_task is not None and not self._step_task.done():
            self._step_request_count += 1
            return
        self._create_step_task()

    async def _step(self) -> None:
        """Execute one agent step."""
        from backend.core.constants import DEFAULT_STEP_TASK_LIVENESS_SECONDS
        from backend.core.llm_step_timeout import resolve_step_task_liveness_seconds

        self.services.retry.ensure_worker_started()

        step_liveness_seconds = resolve_step_task_liveness_seconds(
            getattr(self, 'agent', None),
            default_liveness_seconds=DEFAULT_STEP_TASK_LIVENESS_SECONDS,
        )

        async with self._step_lock:
            self._step_owner_task = asyncio.current_task()
            try:
                await self._drain_steps(step_liveness_seconds)
            finally:
                self._step_owner_task = None
                if not self._closed and self._step_request_count > 0:
                    asyncio.get_event_loop().call_soon(self._create_step_task)

    async def _drain_steps(self, step_liveness_seconds: float) -> None:
        drained_count = 0
        while drained_count < DEFAULT_AGENT_STEP_DRAIN_LIMIT:
            drained_count += 1
            try:
                await asyncio.wait_for(
                    self._step_inner(), timeout=step_liveness_seconds
                )
            except asyncio.TimeoutError:
                await self._handle_liveness_timeout(step_liveness_seconds)
                break
            except asyncio.CancelledError:
                raise
            await asyncio.sleep(0)
            if self._step_request_count <= 0:
                break
            self._step_request_count -= 1
            if not self.step_prerequisites.can_step():
                break

    async def _handle_liveness_timeout(self, step_liveness_seconds: float) -> None:
        logger.error(
            'STEP_TASK_LIVENESS_TIMEOUT: _step_inner did not complete within %.0fs; force-cancelling and clearing pending state.',
            step_liveness_seconds,
            extra={'msg_type': 'STEP_TASK_LIVENESS_TIMEOUT'},
        )
        self._cancel_executor_on_timeout()
        self._clear_pending_state_on_timeout()
        self._emit_liveness_timeout_observation(step_liveness_seconds)

    def _cancel_executor_on_timeout(self) -> None:
        try:
            agent = getattr(self, 'agent', None)
            if agent is None:
                return
            executor = getattr(agent, 'executor', None)
            cancel_fn = (
                getattr(executor, 'cancel_step', None) if executor is not None else None
            )
            if callable(cancel_fn):
                cancel_fn()
        except Exception:
            logger.debug(
                'Failed to cancel executor after step-task liveness timeout',
                exc_info=True,
            )

    def _clear_pending_state_on_timeout(self) -> None:
        try:
            pending_service = getattr(
                getattr(self, 'services', None), 'pending_action', None
            )
            if pending_service is not None:
                pending_service.clear_primary()
        except Exception:
            logger.debug(
                'Failed to clear pending state after step-task liveness timeout',
                exc_info=True,
            )

    def _emit_liveness_timeout_observation(self, step_liveness_seconds: float) -> None:
        try:
            from backend.ledger import EventSource
            from backend.ledger.observation import ErrorObservation

            self.event_stream.add_event(
                ErrorObservation(
                    content=f'Step task exceeded the liveness ceiling of {step_liveness_seconds:.0f}s and was force-cancelled. Pending state was cleared; the next step will retry. The underlying cause is a hang in the agent loop — check the log for the last completed step.',
                    error_id='STEP_TASK_LIVENESS_TIMEOUT',
                    notify_ui_only=True,
                ),
                EventSource.ENVIRONMENT,
            )
        except Exception:
            logger.debug(
                'Failed to emit STEP_TASK_LIVENESS_TIMEOUT observation', exc_info=True
            )

    async def _step_inner_connect_and_check(self, _step_inner_start: float) -> bool:
        """Connect runtime and check prerequisites. Returns False if should exit."""
        set_step_phase('step_inner:ensure_runtime_connected')
        await self._ensure_runtime_connected()
        logger.debug(
            '_step_inner: _ensure_runtime_connected done in %.3fs',
            _step_inner_start,
            extra={'msg_type': 'STEP_INNER_RUNTIME_CONNECTED'},
        )

        set_step_phase('step_inner:check_prerequisites')
        if not self.step_prerequisites.can_step():
            logger.debug(
                '_step_inner EXIT (prereq not met) after %.3fs',
                _step_inner_start,
                extra={'msg_type': 'STEP_INNER_EXIT_PREREQ'},
            )
            return False

        self._log_step_info()
        self._maybe_emit_persistence_degraded_warning()
        self._sync_budget_flag_with_metrics()

        set_step_phase('step_inner:step_guard')
        if not await self.step_guard.ensure_can_step():
            pass

        set_step_phase('step_inner:control_flags')
        if not await self._run_control_flags_safely():
            logger.debug(
                '_step_inner EXIT (control flags) after %.3fs',
                _step_inner_start,
                extra={'msg_type': 'STEP_INNER_EXIT_CONTROL'},
            )
            return False

        return True

    async def _step_inner_get_action(self, _step_inner_start: float) -> Action | None:
        """Get next action from execution queue. Returns None if should exit."""
        set_step_phase('step_inner:get_next_action')
        action = await self.action_execution.get_next_action()
        logger.debug(
            '_step_inner: get_next_action returned %s after %.3fs',
            type(action).__name__ if action is not None else 'None',
            _step_inner_start,
            extra={'msg_type': 'STEP_INNER_GOT_ACTION'},
        )
        if action is None:
            set_step_phase('step_inner:no_action_recovery')
            if not self.action_execution.consume_expected_no_action_recovery():
                await self.action_execution.handle_unexpected_no_action_while_running()
            logger.debug(
                '_step_inner EXIT (no action) after %.3fs',
                _step_inner_start,
                extra={'msg_type': 'STEP_INNER_EXIT_NO_ACTION'},
            )
            return None
        return action

    async def _step_inner_execute_action(
        self, action: Action, _step_inner_start: float
    ) -> None:
        """Execute the action and handle post-execution state."""
        if self.services.retry.retry_count > 0:
            logger.debug(
                'Resetting retry count from %d to 0 after successful execution',
                self.services.retry.retry_count,
            )
            self.services.retry.reset_retry_metrics()

        if self.get_agent_state() != AgentState.RUNNING:
            logger.info('Agent is no longer running, skipping action execution.')
            return

        action_label = getattr(action, 'action', None) or type(action).__name__
        set_step_phase(f'step_inner:execute_action:{action_label}')
        await self.action_execution.execute_action(action)
        logger.debug(
            '_step_inner: execute_action returned after %.3fs for %s',
            _step_inner_start,
            type(action).__name__,
            extra={'msg_type': 'STEP_INNER_EXECUTED_ACTION'},
        )
        extra_data = getattr(self.state, 'extra_data', None)
        if isinstance(extra_data, dict):
            extra_data.pop('__survivable_error_consecutive', None)

    async def _step_inner_handle_message_action(
        self, action: Action, _step_inner_start: float
    ) -> bool:
        """Handle MessageAction special cases. Returns True if should exit."""
        if isinstance(action, MessageAction) and action.source == EventSource.AGENT:
            if action.wait_for_response:
                if self.get_agent_state() == AgentState.RUNNING:
                    set_step_phase('step_inner:await_user_input')
                    await self.set_agent_state_to(AgentState.AWAITING_USER_INPUT)

        if isinstance(action, MessageAction) and bool(
            getattr(action, 'final_response', False)
        ):
            set_step_phase('step_inner:finish')
            with contextlib.suppress(Exception):
                clear_queued_actions = getattr(self.agent, 'clear_queued_actions', None)
                if callable(clear_queued_actions):
                    clear_queued_actions(reason='finish_action_dispatched')
            await self._drain_step_barrier()
            set_step_phase('step_inner:post_execution')
            await self._handle_post_execution()
            logger.debug(
                '_step_inner EXIT (finish branch) after %.3fs',
                _step_inner_start,
                extra={'msg_type': 'STEP_INNER_EXIT_FINISH'},
            )
            return True
        return False

    async def _step_inner_drain_batch(self) -> None:
        """Drain queued non-blocking actions from the same LLM response."""
        set_step_phase('step_inner:drain_batch')
        self._draining_batch = True
        try:
            if not self._pending_action and not await self._try_parallel_read_batch():
                while self._can_drain_pending():
                    drain_action = await self.action_execution.get_next_action()
                    if drain_action is None:
                        break
                    if self.get_agent_state() != AgentState.RUNNING:
                        logger.info('Agent is no longer running, stopping drain.')
                        break
                    drain_label = (
                        getattr(drain_action, 'action', None)
                        or type(drain_action).__name__
                    )
                    set_step_phase(f'step_inner:drain_execute:{drain_label}')
                    await self.action_execution.execute_action(drain_action)
                    await self._drain_step_barrier()
        finally:
            self._draining_batch = False

    async def _step_inner_schedule_next(self) -> None:
        """Schedule the next step if agent is still running."""
        set_step_phase('step_inner:schedule_next')
        await self._drain_step_barrier()
        if self.get_agent_state() == AgentState.RUNNING and not self._closed:
            self.schedule_step_soon()

    async def _step_inner(self) -> None:
        """Inner step logic, guarded by _step_lock."""
        import time as _t

        _step_inner_start = _t.monotonic()
        set_step_phase('step_inner:enter')
        try:
            logger.debug(
                '_step_inner ENTER (sid=%s)',
                getattr(self, 'sid', '?'),
                extra={'msg_type': 'STEP_INNER_ENTER'},
            )

            if not await self._step_inner_connect_and_check(_step_inner_start):
                return

            action = await self._step_inner_get_action(_step_inner_start)
            if action is None:
                return

            await self._step_inner_execute_action(action, _step_inner_start)

            if await self._step_inner_handle_message_action(action, _step_inner_start):
                return

            set_step_phase('step_inner:post_execution')
            await self._handle_post_execution()

            await self._step_inner_drain_batch()

            set_step_phase('step_inner:post_execution_after_drain')
            await self._handle_post_execution()
            logger.debug(
                '_step_inner EXIT (normal) after %.3fs',
                _step_inner_start,
                extra={'msg_type': 'STEP_INNER_EXIT'},
            )

            await self._step_inner_schedule_next()
        finally:
            clear_step_phase()

    # ------------------------------------------------------------------ #
    # Independent watchdog timer for stall detection
    # ------------------------------------------------------------------ #

    def _start_watchdog(self) -> None:
        """Start the independent watchdog background task.

        The watchdog runs on the main event loop and periodically checks
        whether ``step()`` has been called recently.  If the agent is in
        RUNNING state but no step has occurred within the configured timeout,
        the watchdog issues ``schedule_step_soon()`` to recover.

        This is a safety net for the case where the step loop stops running
        entirely (e.g. due to an unhandled exception in ``_on_event``).
        The existing watchdog inside ``_step_inner`` cannot detect this case
        because it only runs when ``_step_inner`` runs.
        """
        if self._watchdog_task is not None and not self._watchdog_task.done():
            return
        import time as _time

        self._watchdog_last_step_ts = _time.monotonic()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = get_main_event_loop()
        if loop is None or not loop.is_running():
            return
        from backend.utils.async_utils import create_tracked_task

        self._watchdog_task = create_tracked_task(
            self._watchdog_loop(),
            name='agent-watchdog',
        )

    def _stop_watchdog(self) -> None:
        """Cancel the watchdog background task."""
        task = getattr(self, '_watchdog_task', None)
        if task is not None and not task.done():
            task.cancel()
        self._watchdog_task = None

    async def _watchdog_loop(self) -> None:
        """Background loop that checks for step() progress at regular intervals."""
        import time as _time

        check_interval = 10.0
        timeout = (
            getattr(self, '_watchdog_timeout', None)
            or self.config.circuit_breaker.no_step_progress_timeout_seconds
        )
        if timeout <= 0:
            return
        cooldown = self.config.circuit_breaker.auto_recover_cooldown_seconds
        auto_recover_attempted = False
        auto_recover_ts = 0.0

        try:
            while not self._closed:
                await asyncio.sleep(check_interval)
                state = self.get_agent_state()
                if state != AgentState.RUNNING:
                    self._watchdog_last_step_ts = _time.monotonic()
                    auto_recover_attempted = False
                    continue

                elapsed = _time.monotonic() - self._watchdog_last_step_ts
                if elapsed < timeout:
                    continue

                now = _time.monotonic()
                if not auto_recover_attempted or (now - auto_recover_ts) > cooldown:
                    logger.warning(
                        'INDEPENDENT WATCHDOG: no step() call for %.1fs in RUNNING; '
                        'issuing schedule_step_soon() to recover',
                        elapsed,
                    )
                    self._watchdog_last_step_ts = now
                    auto_recover_attempted = True
                    auto_recover_ts = now
                    try:
                        self.schedule_step_soon()
                    except Exception:
                        pass
                else:
                    logger.error(
                        'INDEPENDENT WATCHDOG: auto-recover did not help after %.1fs; '
                        'forcing ERROR state to break the stall',
                        elapsed,
                    )
                    try:
                        await self.set_agent_state_to(AgentState.ERROR)
                    except Exception:
                        pass
                    return
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.debug('Watchdog loop exited: %s', exc)

    def _record_watchdog_step(self) -> None:
        """Record that step() was called, resetting the watchdog timer."""
        import time as _time

        self._watchdog_last_step_ts = _time.monotonic()

    async def close(self, set_stop_state: bool = True) -> None:
        """Closes the agent controller, canceling any ongoing tasks and unsubscribing from the event stream.

        Note that it's fairly important that this closes properly, otherwise the state is incomplete.
        """
        self._lifecycle = LifecyclePhase.CLOSING
        self._stop_watchdog()
        # C-P1-1: snapshot final state for post-mortem rollback.
        try:
            self._create_phase_boundary_checkpoint('active_to_closing')
        except Exception:
            pass
        stream = self.event_stream
        try:
            self._step_request_count = 0
            if self._step_task is not None and not self._step_task.done():
                self._step_task.cancel()
                try:
                    await asyncio.wait_for(self._step_task, timeout=10.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass
            pending_service = self.services.pending_action
            if pending_service is not None:
                pending_service.shutdown()
            # Signal the executor to stop streaming immediately so no more
            # StreamingChunkAction events are emitted after agent stop.
            agent = getattr(self, 'agent', None)
            if agent is not None:
                executor = getattr(agent, 'executor', None)
                if executor is not None:
                    cancel_fn = getattr(executor, 'cancel_step', None)
                    if cancel_fn is not None:
                        cancel_fn()
            if set_stop_state:
                await self.set_agent_state_to(AgentState.STOPPED)
            self.state_tracker.close(stream)
            stream.unsubscribe(EventStreamSubscriber.AGENT_CONTROLLER, self.id or '')
            await self.services.retry.shutdown()
        finally:
            # Explicitly close the stream to avoid weakref finalizer warnings:
            # "EventStream ... was GC'd without close(); resources may leak."
            with contextlib.suppress(Exception):
                stream.close()
            self._lifecycle = LifecyclePhase.CLOSED

    @property
    def _closed(self) -> bool:
        """Read-only view that is True when lifecycle is CLOSING or CLOSED."""
        return self._lifecycle in (LifecyclePhase.CLOSING, LifecyclePhase.CLOSED)


# --------------------------------------------------------------------------- #
# Backward-compat re-exports (used by tests via monkeypatch.setattr).
# --------------------------------------------------------------------------- #
