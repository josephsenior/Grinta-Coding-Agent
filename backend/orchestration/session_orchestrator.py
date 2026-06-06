"""Agent controller orchestration, logging, and execution helpers."""

from __future__ import annotations

import asyncio
import contextlib
import threading
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
        # Separate threading-safe gate for the sync step() entry point.
        # EventStream callbacks arrive from a thread pool; without this lock
        # two concurrent calls can both see _step_task as done and both create
        # step tasks, violating the "only one step at a time" invariant.
        self._step_gate = threading.Lock()
        # When a step is requested while another is running, this flag ensures
        # the dropped request is re-queued after the current step completes.
        # Protected by _step_lock to avoid races with drain_loop's read/write.
        self._step_pending = False
        # Monotonic counter incremented every time ``step()`` is asked to
        # re-queue a request (i.e. an in-flight step task is still alive).
        # ``_step`` captures this counter on entry and only clears
        # ``_step_pending`` in its ``finally`` if the counter is unchanged
        # — this prevents the racy ``_step_pending`` wipe documented in
        # :meth:`schedule_step_soon`.  Even if Edit 1 (use
        # ``schedule_step_soon`` from ``_on_event``) is somehow bypassed,
        # this counter is the second line of defence.
        self._step_seq: int = 0
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

        Thread-safe: the _step_gate is held for the entire task-creation
        window so that call_soon_threadsafe + _create_step_task is atomic.
        Only one step task can be created even across concurrent calls.
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

        # Atomic gate: prevents two threads from both seeing _step_task as done
        # and both creating step tasks.  The gate is held for the entire
        # call_soon_threadsafe window so no other thread can interleave.
        with self._step_gate:
            if self._step_task and not self._step_task.done():
                # Bump _step_seq so the in-flight ``_step`` task's ``finally``
                # block does NOT clear ``_step_pending`` (it's a fresh
                # re-queue that arrived during the task's teardown window).
                self._step_seq += 1
                self._step_pending = True
                return

            main_loop = get_main_event_loop()
            if main_loop is not None and main_loop.is_running():
                main_loop.call_soon_threadsafe(self._create_step_task)
            else:
                self._create_step_task()

    async def _step(self) -> None:
        """Execute one agent step.

        Detects stuck agents and enforces iteration and task budget limits.
        When the agent returns a non-blocking action (e.g. AgentThinkAction)
        and has more queued actions from the same LLM response, those are
        drained immediately without re-entering the full polling cycle.

        If another step is already running, marks _step_pending so the
        current step will re-trigger after it completes — no events are
        silently dropped.
        """
        async with self._step_lock:
            self._step_owner_task = asyncio.current_task()
            # Capture the ``_step_seq`` counter on entry.  If a fresh
            # ``step()`` call bumps the counter while we're still inside
            # the drain loop, the ``finally`` block must NOT clobber the
            # corresponding ``_step_pending = True`` — that fresh request
            # belongs to a newer step and must survive our teardown.
            entry_seq = self._step_seq
            try:
                drained_count = 0
                while drained_count < DEFAULT_AGENT_STEP_DRAIN_LIMIT:
                    drained_count += 1
                    await self._step_inner()
                    await asyncio.sleep(0)
                    if not self._step_pending:
                        break
                    self._step_pending = False
                    if not self.step_prerequisites.can_step():
                        break
            finally:
                self._step_owner_task = None
                # Only clear _step_pending if no fresh request arrived
                # during our teardown.  This closes the race that
                # ``schedule_step_soon`` (and the previous direct
                # ``self.step()`` in ``_on_event``) used to lose requests
                # to the ``finally`` wipe.
                if self._step_seq == entry_seq:
                    self._step_pending = False
                else:
                    # Newer request arrived — keep _step_pending set so
                    # the new _step task (already created via
                    # call_soon_threadsafe) sees it on its first pass.
                    self._step_pending = True

    async def _step_inner(self) -> None:
        """Inner step logic, guarded by _step_lock."""
        await self._ensure_runtime_connected()

        if not self.step_prerequisites.can_step():
            return

        self._log_step_info()
        self._sync_budget_flag_with_metrics()

        if not await self.step_guard.ensure_can_step():
            # Disabled step guard for now
            pass

        if not await self._run_control_flags_safely():
            return

        action = await self.action_execution.get_next_action()
        if action is None:
            if not self.action_execution.consume_expected_no_action_recovery():
                await self.action_execution.handle_unexpected_no_action_while_running()
            return

        # Reset retry count on successful action execution
        # This prevents getting stuck if a previous error has been resolved
        if self.services.retry.retry_count > 0:
            logger.debug(
                'Resetting retry count from %d to 0 after successful execution',
                self.services.retry.retry_count,
            )
            self.services.retry.reset_retry_metrics()

        if self.get_agent_state() != AgentState.RUNNING:
            logger.info('Agent is no longer running, skipping action execution.')
            return

        await self.action_execution.execute_action(action)
        extra_data = getattr(self.state, 'extra_data', None)
        if isinstance(extra_data, dict):
            extra_data.pop('__survivable_error_consecutive', None)

        # P1-B: When the agent returns a MessageAction with wait_for_response,
        # the state must be transitioned to AWAITING_USER_INPUT synchronously
        # here (after the action is dispatched) rather than relying on the
        # async on_event handler. If we don't, the subsequent "schedule next
        # step" check below will see state still RUNNING and queue another LLM
        # call, creating a spurious step task that blocks the next user message.
        if isinstance(action, MessageAction) and action.source == EventSource.AGENT:
            if action.wait_for_response:
                if self.get_agent_state() == AgentState.RUNNING:
                    await self.set_agent_state_to(AgentState.AWAITING_USER_INPUT)
        # Finish must terminate the current response immediately. Any queued
        # follow-up actions from the same LLM response are stale once finish was
        # chosen, so drop them and do not schedule another step from this turn.
        if (
            isinstance(action, MessageAction)
            and bool(getattr(action, 'final_response', False))
        ):
            with contextlib.suppress(Exception):
                clear_queued_actions = getattr(self.agent, 'clear_queued_actions', None)
                if callable(clear_queued_actions):
                    clear_queued_actions(reason='finish_action_dispatched')
            from backend.utils.async_utils import drain_background_tasks

            await drain_background_tasks(max_rounds=2, timeout=2.0)
            await self._handle_post_execution()
            return
        await self._handle_post_execution()

        # Batch-drain queued non-blocking actions from the same LLM response.
        # After a non-runnable action (e.g. AgentThinkAction), no pending_action
        # is set, so we can immediately process the next queued action without
        # waiting for the full polling cycle.
        #
        # P2-B: If all remaining queued actions are parallel-safe (reads, thinks,
        # searches), execute them concurrently via asyncio.gather. The pending
        # action service already tracks multiple outstanding actions by stream ID,
        # so concurrent execute_action calls are safe as long as each action gets
        # a unique ID (guaranteed by EventStream.add_event).
        self._draining_batch = True
        try:
            if not self._pending_action and not await self._try_parallel_read_batch():
                # Fall through to serial drain for mixed workloads.
                while self._can_drain_pending():
                    action = await self.action_execution.get_next_action()
                    if action is None:
                        break
                    if self.get_agent_state() != AgentState.RUNNING:
                        logger.info('Agent is no longer running, stopping drain.')
                        break
                    await self.action_execution.execute_action(action)
                    # Drain background _on_event tasks so state.history is
                    # updated before the next get_next_action() → astep()
                    # → condense_history() check.
                    from backend.utils.async_utils import drain_background_tasks

                    await drain_background_tasks(max_rounds=2, timeout=2.0)
        finally:
            self._draining_batch = False
        # Deferred condensation check after batch drain completes.
        await self._handle_post_execution()

        # After processing non-runnable actions (e.g. AgentThinkAction), no
        # pending action is set and the runtime may never produce an observation
        # that would re-trigger the step loop.  Schedule the next step so the
        # agent can proceed to the LLM call instead of stalling indefinitely.
        if not self._pending_action:
            # Drain background _on_event tasks so state transitions from agent
            # messages (e.g. wait_for_response handoffs) are fully processed
            # before deciding whether to queue the next LLM call.
            from backend.utils.async_utils import drain_background_tasks

            await drain_background_tasks(max_rounds=2, timeout=2.0)
            if (
                not self._pending_action
                and self.get_agent_state() == AgentState.RUNNING
                and not self._closed
            ):
                self.schedule_step_soon()

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
        timeout = getattr(
            self, '_watchdog_timeout', None
        ) or self.config.circuit_breaker.no_step_progress_timeout_seconds
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
            self._step_pending = False
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
