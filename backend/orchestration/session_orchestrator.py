"""Agent controller orchestration, logging, and execution helpers."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import threading
import time
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any, cast

from backend.utils.async_utils import (
    get_main_event_loop,
    run_or_schedule,
    set_main_event_loop,
)

if TYPE_CHECKING:
    from backend.core.config import AgentConfig, LLMConfig
    from backend.ledger.event import Event
    from backend.orchestration.conversation_stats import ConversationStats
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
    SystemMessageAction,
)
from backend.ledger.observation import (
    AgentStateChangedObservation,
    ErrorObservation,
    Observation,
)
from backend.ledger.observation_cause import attach_observation_cause
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
from backend.orchestration.state.state import State
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


class SessionOrchestrator(SessionOrchestratorAccessorsMixin):
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

    # Dynamic attributes set by LifecycleService / AutonomyService during init
    user_id: str | None
    file_store: FileStore | None
    headless_mode: bool
    status_callback: Callable | None
    security_analyzer: SecurityAnalyzer | None
    confirmation_mode: bool
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
            config.confirmation_mode,
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

    def _initialize_operation_pipeline(self) -> None:
        """Build the default tool pipeline directly on the controller.

        Middleware are ordered by responsibility. Pipeline runs execute() then observe():
        1. SafetyValidatorMiddleware - blocks dangerous actions (file deletions outside workspace, etc.)
        2. BlackboardMiddleware - shares state between concurrent tool invocations
        3. CircuitBreakerMiddleware - prevents repeated tool failures from blocking progress
        4. ProgressPolicyMiddleware - enforces progress checks (e.g., max iterations)
        5. CostQuotaMiddleware - tracks and limits LLM spend
        6. ContextWindowMiddleware - prevents context window overflow
        7. RollbackMiddleware - creates checkpoints before risky operations for recovery
        8. DestructiveCommandMiddleware - high-priority checkpoints before shell destructive ops
        9. PreExecDiffMiddleware - computes diff before action executes for user preview
        10. AutoCheckMiddleware - runs auto-checks after tool execution
        11. FileStateMiddleware - tracks file modifications for state management
        12. LoggingMiddleware, TelemetryMiddleware - observability (always last in execute)
        13. ToolResultValidator - validates results after all observe() hooks complete
        """
        from backend.orchestration.file_state_tracker import FileStateMiddleware
        from backend.orchestration.middleware.destructive_command import (
            DestructiveCommandMiddleware,
        )
        from backend.orchestration.pre_exec_diff import PreExecDiffMiddleware
        from backend.orchestration.rollback_middleware import RollbackMiddleware
        from backend.orchestration.tool_pipeline import (
            AutoCheckMiddleware,
            BlackboardMiddleware,
            CircuitBreakerMiddleware,
            ContextWindowMiddleware,
            CostQuotaMiddleware,
            LoggingMiddleware,
            ProgressPolicyMiddleware,
            SafetyValidatorMiddleware,
            TelemetryMiddleware,
        )
        from backend.orchestration.tool_result_validator import ToolResultValidator

        middlewares = [
            SafetyValidatorMiddleware(self),
            BlackboardMiddleware(self),
            CircuitBreakerMiddleware(self),
            ProgressPolicyMiddleware(),
            CostQuotaMiddleware(self),
            ContextWindowMiddleware(self),
            RollbackMiddleware(),
            DestructiveCommandMiddleware(),
            PreExecDiffMiddleware(),
            AutoCheckMiddleware(),
        ]
        file_state_mw = FileStateMiddleware()
        middlewares.append(file_state_mw)
        self._file_state_tracker = file_state_mw.tracker
        middlewares.extend([LoggingMiddleware(self), TelemetryMiddleware(self)])
        middlewares.append(ToolResultValidator())
        self.services.context.initialize_operation_pipeline(middlewares)
        # Stash the rollback middleware reference for phase-boundary checkpoints.
        self._rollback_middleware = next(
            (m for m in middlewares if isinstance(m, RollbackMiddleware)),
            None,
        )

    def _create_phase_boundary_checkpoint(self, label: str) -> None:
        """Create a ``phase_boundary`` checkpoint at lifecycle transitions.

        Reuses the existing ``RollbackMiddleware``'s ``RollbackManager`` so we
        don't snapshot through a second instance (which would race on the
        on-disk ``checkpoints.json`` file).  Failures are non-fatal — a missed
        phase-boundary checkpoint must never block a lifecycle transition —
        but they are surfaced at WARNING level because rollback consumers
        depend on these checkpoints existing for recovery.
        """
        mw = getattr(self, '_rollback_middleware', None)
        if mw is None:
            logger.info(
                'Phase-boundary checkpoint at %s skipped: no RollbackMiddleware '
                'is registered. Rollback to this transition will not be possible.',
                label,
            )
            return
        try:
            from backend.orchestration.tool_pipeline import ToolInvocationContext

            ctx = ToolInvocationContext(controller=self, action=None, state=None)  # type: ignore[arg-type]
            manager = mw._get_manager(ctx)  # type: ignore[attr-defined]
            if manager is None:
                logger.info(
                    'Phase-boundary checkpoint at %s skipped: RollbackManager '
                    'unavailable. Rollback to this transition will not be possible.',
                    label,
                )
                return
            cid = manager.create_checkpoint(
                description=f'phase boundary: {label}',
                checkpoint_type='phase_boundary',
                metadata={
                    'phase_label': label,
                    'session_id': getattr(self, 'id', 'unknown'),
                },
                use_git=False,
            )
            logger.debug('Phase-boundary checkpoint %s created at %s', cid, label)
        except Exception:
            logger.warning(
                'Phase-boundary checkpoint creation failed at %s — rollback to '
                'this transition will not be possible.',
                label,
                exc_info=True,
            )

    def handle_blocked_invocation(
        self,
        action: Action,
        ctx: ToolInvocationContext,
    ) -> None:
        """Clean up and emit an error observation when middleware blocks a tool.

        Agent-guidance blocks (``block(..., agent_only=True)``) still reach the
        model but are not rendered in the CLI transcript.
        """
        from backend.ledger.observation_cause import attach_observation_cause
        from backend.orchestration.tool_telemetry import ToolTelemetry

        self._cleanup_action_context(ctx, action=action)

        try:
            ToolTelemetry.get_instance().on_blocked(ctx, reason=ctx.block_reason)
        except Exception:
            logger.debug('Failed to record telemetry for blocked action', exc_info=True)

        if not ctx.metadata.get('handled'):
            error_content = ctx.block_reason or 'Action blocked by middleware pipeline.'
            error_obs = ErrorObservation(
                content=error_content,
                error_id='TOOL_PIPELINE_BLOCKED',
                agent_only=bool(ctx.metadata.get('block_agent_only')),
            )
            attach_observation_cause(
                error_obs,
                action,
                context='session_orchestrator.handle_blocked_invocation',
            )
            self.event_stream.add_event(error_obs, EventSource.ENVIRONMENT)

        self.services.pending_action.set(None)

    def _sync_budget_flag_with_metrics(self) -> None:
        """Keep the budget control flag aligned with accumulated metrics."""
        tracker = getattr(self, 'state_tracker', None)
        if tracker and hasattr(tracker, 'sync_budget_flag_with_metrics'):
            tracker.sync_budget_flag_with_metrics()

    def _register_action_context(
        self, action: Action, ctx: ToolInvocationContext
    ) -> None:
        """Register an invocation context before execution."""
        if hasattr(self, '_action_contexts_by_object'):
            self._action_contexts_by_object[id(action)] = ctx

    def _bind_action_context(self, action: Action, ctx: ToolInvocationContext) -> None:
        """Bind a context to an action's event ID after emission."""
        if not hasattr(self, '_action_contexts_by_event_id'):
            return
        ctx.action_id = action.id
        if ctx.action_id is not None:
            self._action_contexts_by_event_id[ctx.action_id] = ctx
        if hasattr(self, '_action_contexts_by_object'):
            with contextlib.suppress(KeyError):
                self._action_contexts_by_object.pop(id(action))

    def _cleanup_action_context(
        self,
        ctx: ToolInvocationContext,
        *,
        action: Action | None = None,
    ) -> None:
        """Remove context bookkeeping entries."""
        if hasattr(self, '_action_contexts_by_object'):
            if action is not None:
                with contextlib.suppress(KeyError):
                    self._action_contexts_by_object.pop(id(action))
            else:
                keys_to_remove = [
                    key
                    for key, value in self._action_contexts_by_object.items()
                    if value is ctx
                ]
                for key in keys_to_remove:
                    with contextlib.suppress(KeyError):
                        self._action_contexts_by_object.pop(key)
        if hasattr(self, '_action_contexts_by_event_id') and ctx.action_id is not None:
            with contextlib.suppress(KeyError):
                self._action_contexts_by_event_id.pop(ctx.action_id)

    def _add_system_message(self) -> None:
        """Add system message to event stream if not already present.

        Checks if a system message has already been added for this agent session.
        If not, retrieves the agent's system message and adds it to the event stream.
        """
        for event in self.event_stream.search_events(start_id=self.state.start_id):
            if isinstance(event, MessageAction) and event.source == EventSource.USER:
                return
            if isinstance(event, SystemMessageAction):
                return
        system_message = self.agent.get_system_message()
        if system_message and system_message.content:
            preview = (
                f'{system_message.content[:50]}...'
                if len(system_message.content) > 50
                else system_message.content
            )
            logger.debug('System message: %s', preview)
            self.event_stream.add_event(system_message, EventSource.AGENT)

    @property
    def _closed(self) -> bool:
        """Read-only view that is True when lifecycle is CLOSING or CLOSED."""
        return self._lifecycle in (LifecyclePhase.CLOSING, LifecyclePhase.CLOSED)

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

    def log(self, level: str, message: str, extra: dict | None = None) -> None:
        """Logs a message to the agent controller's logger.

        Args:
            level (str): The logging level to use (e.g., 'info', 'debug', 'error').
            message (str): The message to log.
            extra (dict | None, optional): Additional fields to log. Includes session_id by default.

        """
        message = f'[Agent Controller {self.id}] {message}'
        if extra is None:
            extra = {}
        extra_merged = {'session_id': self.id, **extra}
        getattr(logger, level)(message, extra=extra_merged, stacklevel=2)

    async def _react_to_exception(self, e: Exception) -> None:
        """Delegate exception handling to the recovery service."""
        await self.services.recovery.react_to_exception(e)

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

    def on_event(self, event: Event) -> None:
        """Callback from the event stream. Notifies the controller of incoming events."""
        if self._closed:
            return
        run_or_schedule(self._on_event(event))

    def _schedule_coroutine(self, coro: Coroutine[Any, Any, Any]) -> None:
        """Schedule a coroutine using the current or new event loop."""
        run_or_schedule(coro)

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
        if not self._closed and self.should_step(event):
            self.step()

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

    async def stop(self) -> None:
        """Stop the agent, best-effort kill runtime processes, and clear pending actions."""
        logger.info('Stopping agent...')
        self._step_pending = False
        # Signal the executor to stop streaming immediately.
        agent = getattr(self, 'agent', None)
        if agent is not None:
            executor = getattr(agent, 'executor', None)
            if executor is not None:
                cancel_fn = getattr(executor, 'cancel_step', None)
                if cancel_fn is not None:
                    cancel_fn()
        runtime = getattr(self, 'runtime', None)
        hard_kill = getattr(runtime, 'hard_kill', None)
        if callable(hard_kill):
            try:
                hard_kill_result = _invoke_zero_arg_callback(
                    cast(Callable[[], object], hard_kill)
                )
                if inspect.isawaitable(hard_kill_result):
                    await hard_kill_result
            except Exception:
                logger.warning('Runtime hard_kill failed during stop()', exc_info=True)

        # 2. Update state to STOPPED
        await self.set_agent_state_to(AgentState.STOPPED)

        # 3. Ensure any pending actions are cleared or marked as cancelled?
        self._pending_action = None

    async def _ensure_runtime_connected(self) -> None:
        """Restore execution backend if disconnected (e.g. after hard_kill/interrupt)."""
        runtime = getattr(self, 'runtime', None)
        if runtime is None:
            return

        # Check if already initialized to avoid redundant connect calls.
        if hasattr(runtime, 'runtime_initialized'):
            try:
                if runtime.runtime_initialized:
                    return
            except Exception:
                logger.debug('runtime_initialized check failed', exc_info=True)

        connect_fn = getattr(runtime, 'connect', None)
        if callable(connect_fn):
            logger.info('Restoring runtime connection...')
            await connect_fn()

    async def set_agent_state_to(self, new_state: AgentState) -> None:
        """Delegate to the state transition service for consistency."""
        await self.services.state.set_agent_state(new_state)

    def get_agent_state(self) -> AgentState:
        """Returns the current state of the agent.

        Returns:
            AgentState: The current state of the agent.

        """
        return self.state.agent_state

    def _log_step_info(self) -> None:
        """Log step information for debugging."""
        local_step = self.state.get_local_step()
        global_step = self.state.iteration_flag.current_value
        self.log(
            'debug',
            f'LOCAL STEP {local_step} GLOBAL STEP {global_step}',
            extra={'msg_type': 'STEP'},
        )

    @property
    def _step_lock(self) -> asyncio.Lock:
        """Lazily initialize the lock on the current event loop."""
        current_loop = None
        with contextlib.suppress(RuntimeError):
            current_loop = asyncio.get_running_loop()
        if (
            self._step_lock_instance is None
            or (
                current_loop is not None
                and self._step_lock_loop is not None
                and current_loop is not self._step_lock_loop
            )
        ):
            self._step_lock_instance = asyncio.Lock()
            self._step_lock_loop = current_loop
        return self._step_lock_instance

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

    async def reset_controller(self) -> None:
        owner = self._step_owner_task
        if owner is not None and asyncio.current_task() is owner:
            self._reset()
            return
        async with self._step_lock:
            self._reset()

    async def _step_inner(self) -> None:
        """Inner step logic, guarded by _step_lock."""
        await self._ensure_runtime_connected()

        if not self.step_prerequisites.can_step():
            return

        self._log_step_info()
        self._sync_budget_flag_with_metrics()

        if not await self.step_guard.ensure_can_step():
            return

        if not await self._run_control_flags_safely():
            return

        action = await self.action_execution.get_next_action()
        if action is None:
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
                        return await asyncio.to_thread(
                            compactor.compacted_history, state_copy
                        )

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

    def get_state(self) -> State:
        """Returns the current running state object.

        Returns:
            State: The current state object.

        """
        return self.state

    def set_initial_state(
        self,
        state: State | None,
        conversation_stats: ConversationStats,
        max_iterations: int,
        max_budget_per_task: float | None,
        confirmation_mode: bool = False,
    ) -> None:
        """Set the initial state for the agent controller.

        Args:
            state: Initial state object (None for new conversations)
            conversation_stats: Statistics tracker for the conversation
            max_iterations: Maximum number of agent iterations allowed
            max_budget_per_task: Maximum budget in USD per task
            confirmation_mode: Whether to require user confirmation for actions

        """
        self.state_tracker.set_initial_state(
            self.id or '',
            state,
            conversation_stats,
            max_iterations,
            max_budget_per_task,
            confirmation_mode,
        )
        self.state_tracker._init_history(self.event_stream)  # type: ignore[attr-defined]  # bootstrap wiring

    def get_transcript(self, include_screenshots: bool = False) -> list[dict[str, Any]]:
        """Get the complete transcript of agent operations and outcomes.

        Must be called after controller is closed.

        Args:
            include_screenshots: Whether to include screenshot data in transcript

        Returns:
            List of transcript records as dictionaries

        """
        if self._lifecycle != LifecyclePhase.CLOSED:
            raise RuntimeError(
                f'get_transcript() requires the controller to be closed. Current phase: {self._lifecycle.value}'
            )
        return self.state_tracker.get_transcript(include_screenshots)

    def _is_stuck(self) -> bool:
        """Checks if the agent is stuck in a loop.

        Returns:
            bool: True if the agent is stuck, False otherwise.

        """
        return self.services.stuck.is_stuck()

    def __repr__(self) -> str:
        """Get string representation of controller with key state information.

        Returns:
            String representation including ID, agent state, and pending action info

        """
        pending_action_info = '<none>'
        action_service = getattr(self, 'action_service', None)
        if action_service:
            info = action_service.get_pending_action_info()
            if info is not None:
                action, timestamp = info
                action_id = getattr(action, 'id', 'unknown')
                action_type = type(action).__name__
                elapsed_time = time.time() - timestamp
                pending_action_info = (
                    f'{action_type}(id={action_id}, elapsed={elapsed_time:.2f}s)'
                )
        controller_id = getattr(self, 'id', '<uninitialized>')
        agent_obj = getattr(self, 'agent', '<uninitialized>')
        event_stream = getattr(self, 'event_stream', '<uninitialized>')
        state_obj = getattr(self, 'state', '<uninitialized>')
        return (
            f'SessionOrchestrator(id={controller_id}, agent={agent_obj!r}, '
            f'event_stream={event_stream!r}, state={state_obj!r}, '
            f'_pending_action={pending_action_info})'
        )

    def _is_awaiting_observation(self) -> bool:
        """Check if agent is waiting for an observation to complete current action.

        Searches backward through event stream to find most recent agent state change.

        Returns:
            True if agent is in RUNNING state (awaiting observation)

        """
        events = self.event_stream.search_events(reverse=True)
        return next(
            (
                event.agent_state == AgentState.RUNNING
                for event in events
                if isinstance(event, AgentStateChangedObservation)
            ),
            False,
        )

    def _first_user_message(
        self, events: list[Event] | None = None
    ) -> MessageAction | None:
        """Get the first user message for this agent.

        The cache is intentionally not used when *events* is passed, as the
        caller supplies an explicit event list that may differ from the stream.
        When the cache is populated from the stream, it is validated against
        the current history to avoid returning a stale reference after trimming.

        Args:
            events: Optional list of events to search through. If None, uses the event stream.

        Returns:
            MessageAction | None: The first user message, or None if no user message found

        """
        if events is not None:
            return next(
                (
                    e
                    for e in events
                    if isinstance(e, MessageAction) and e.source == EventSource.USER
                ),
                None,
            )
        if self._cached_first_user_message is not None:
            if self._cached_first_user_message in self.state.history:
                return self._cached_first_user_message
            self._cached_first_user_message = None
        self._cached_first_user_message = next(
            (
                e
                for e in self.event_stream.search_events(start_id=self.state.start_id)
                if isinstance(e, MessageAction) and e.source == EventSource.USER
            ),
            None,
        )
        return self._cached_first_user_message

    def _get_initial_task(self) -> Any:
        """Get the initial task from first user message.

        Returns:
            Task object or None

        """
        first_msg = self._first_user_message()
        if not first_msg:
            return None

        from backend.validation.task_metadata import parse_task_from_user_message
        from backend.validation.task_validator import Task

        description, meta = parse_task_from_user_message(first_msg.content)
        raw_expected = meta.get('expected_output_files')
        expected_files: list[str] | None = None
        if isinstance(raw_expected, list) and all(
            isinstance(x, str) for x in raw_expected
        ):
            expected_files = list(raw_expected)
        return Task(
            description=description,
            requirements=[],
            acceptance_criteria=[],
            expected_output_files=expected_files,
        )

    def save_state(self) -> None:
        """Save current agent state to persistent storage."""
        self.state_tracker.save_state()

    async def _invoke_audit_callback(
        self,
        callback: Callable[..., Any],
        **kwargs: Any,
    ) -> None:
        """Invoke audit callback and await coroutine results when needed."""
        result = callback(**kwargs)
        if asyncio.iscoroutine(result):
            await result

    async def log_task_audit(
        self, status: str, error_message: str | None = None
    ) -> None:
        """Log the result of a high-level task to the audit store.

        Uses the audit_callback registered during session creation (injected
        by the server layer) so controller never imports server code.
        """
        audit_fn = getattr(self, '_audit_callback', None)
        if audit_fn is None or not callable(audit_fn):
            return
        try:
            task = self._get_initial_task()
            task_name = task.description[:100] if task else 'unknown_task'

            stats = self.state.metrics
            tokens = (
                stats.accumulated_token_usage.prompt_tokens
                + stats.accumulated_token_usage.completion_tokens
            )
            cost = stats.accumulated_cost

            await self._invoke_audit_callback(
                audit_fn,
                conversation_id=self.id,
                task_name=task_name,
                status=status,
                error_message=error_message,
                tokens_used=tokens,
                cost=cost,
            )
        except Exception as e:
            logger.debug('Audit log failed: %s', e)
