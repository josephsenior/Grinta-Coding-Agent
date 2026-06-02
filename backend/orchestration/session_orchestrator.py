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
    PlaybookFinishAction,
)
from backend.orchestration._session_orchestrator_action_mixin import (
    _SessionOrchestratorActionMixin,
)
from backend.orchestration._session_orchestrator_lifecycle_mixin import (
    _SessionOrchestratorLifecycleMixin,
)
from backend.orchestration._session_orchestrator_parallel_mixin import (
    _SessionOrchestratorParallelMixin,
)
from backend.orchestration._session_orchestrator_state_mixin import (
    _SessionOrchestratorStateMixin,
)
from backend.orchestration._session_orchestrator_step_mixin import (
    _SessionOrchestratorStepMixin,
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
        # Suppresses memory-pressure condensation signalling during batch drain
        # so that pending actions are not disrupted mid-batch.
        self._draining_batch = False
        # CLI Ctrl+C: skip pending-unmatched ErrorObservation on next _reset().
        self._suppress_pending_unmatched_error_on_reset: bool = False

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

        # Atomic gate: prevents two threads from both seeing _step_task as done
        # and both creating step tasks.  The gate is held for the entire
        # call_soon_threadsafe window so no other thread can interleave.
        with self._step_gate:
            if self._step_task and not self._step_task.done():
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
                self._step_pending = False

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
        if isinstance(action, PlaybookFinishAction):
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
                self.step()

    async def close(self, set_stop_state: bool = True) -> None:
        """Closes the agent controller, canceling any ongoing tasks and unsubscribing from the event stream.

        Note that it's fairly important that this closes properly, otherwise the state is incomplete.
        """
        self._lifecycle = LifecyclePhase.CLOSING
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
