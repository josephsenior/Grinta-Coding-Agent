"""Agent controller orchestration, logging, and execution helpers."""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any, ClassVar

from backend.utils.async_utils import run_or_schedule

if TYPE_CHECKING:
    from backend.controller.replay import ReplayManager
    from backend.controller.state.state_tracker import StateTracker
    from backend.core.config import AgentConfig, LLMConfig
    from backend.events.event import Event
    from backend.security.analyzer import SecurityAnalyzer
    from backend.server.services.conversation_stats import ConversationStats
    from backend.storage.files import FileStore

from backend.controller.agent import Agent
from backend.controller.controller_config import ControllerConfig, ControllerServices
from backend.controller.memory_pressure import MemoryPressureMonitor
from backend.controller.rate_governor import LLMRateGovernor
from backend.controller.state.state import State
from backend.controller.tool_pipeline import ToolInvocationContext
from backend.core.enums import LifecyclePhase
from backend.core.logger import FORGE_logger as logger
from backend.core.schemas import AgentState
from backend.events import EventSource, EventStream, EventStreamSubscriber
from backend.events.action import (
    Action,
    MessageAction,
    SystemMessageAction,
)
from backend.events.observation import (
    AgentStateChangedObservation,
    ErrorObservation,
    Observation,
)

TRAFFIC_CONTROL_REMINDER = (
    "Please click on resume button if you'd like to continue, or start a new task."
)
ERROR_ACTION_NOT_EXECUTED_STOPPED_ID = "AGENT_ERROR$ERROR_ACTION_NOT_EXECUTED_STOPPED"
ERROR_ACTION_NOT_EXECUTED_ERROR_ID = "AGENT_ERROR$ERROR_ACTION_NOT_EXECUTED_ERROR"
ERROR_ACTION_NOT_EXECUTED_STOPPED = (
    "Stop button pressed. The action has not been executed."
)
ERROR_ACTION_NOT_EXECUTED_ERROR = (
    "The action has not been executed due to a runtime error. "
    "The runtime system may have crashed and restarted due to resource constraints. "
    "Any previously established system state, dependencies, or environment variables "
    "may have been lost."
)


class AgentController:
    """Coordinates agent loop execution, event stream handling, and runtime interactions."""

    config: ControllerConfig
    services: ControllerServices
    _lifecycle_phase: LifecyclePhase = LifecyclePhase.INITIALIZING
    _cached_first_user_message: MessageAction | None = None
    state_tracker: StateTracker
    _replay_manager: ReplayManager
    PENDING_ACTION_TIMEOUT: float = 120.0
    _step_task: asyncio.Task[None] | None = None
    rate_governor: LLMRateGovernor
    memory_pressure: MemoryPressureMonitor
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

    @property
    def id(self) -> str | None:
        return self.config.sid or (
            self.config.event_stream.sid if self.config.event_stream else None
        )

    @property
    def agent(self) -> Agent:
        return self.config.agent

    @property
    def event_stream(self) -> EventStream:
        return self.config.event_stream

    @property
    def state(self) -> State:
        return self.state_tracker.state

    @property
    def conversation_stats(self) -> ConversationStats:
        return self.config.conversation_stats

    @property
    def task_id(self) -> str | None:
        return self.id

    # ------------------------------------------------------------------
    # Service forwarding — maps legacy *_service property names to
    # ControllerServices attribute names.  Keeps the public API stable
    # with zero boilerplate.
    # ------------------------------------------------------------------

    _SERVICE_ALIASES: ClassVar[dict[str, str]] = {
        "action_service": "action",
        "pending_action_service": "pending_action",
        "autonomy_service": "autonomy",
        "iteration_service": "iteration",
        "lifecycle_service": "lifecycle",
        "state_service": "state",
        "retry_service": "retry",
        "recovery_service": "recovery",
        "stuck_service": "stuck",
        "circuit_breaker_service": "circuit_breaker",
        "telemetry_service": "telemetry",
        "observation_service": "observation",
        "task_validation_service": "task_validation",
        # Attributes whose names already match the ControllerServices field:
        "iteration_guard": "iteration_guard",
        "step_guard": "step_guard",
        "step_prerequisites": "step_prerequisites",
        "budget_guard": "budget_guard",
        "exception_handler": "exception_handler",
        "event_router": "event_router",
        "step_decision": "step_decision",
        "action_execution": "action_execution",
    }

    def __getattr__(self, name: str) -> Any:
        """Delegate *_service / guard / handler lookups to ``self.services``."""
        svc_attr = self._SERVICE_ALIASES.get(name)
        if svc_attr is not None:
            # ``self.services`` is set in __init__; access via __dict__
            # to avoid infinite recursion if called before __init__ finishes.
            services = self.__dict__.get("services")
            if services is not None:
                return getattr(services, svc_attr)
        raise AttributeError(
            f"{type(self).__name__!r} object has no attribute {name!r}"
        )

    @property
    def stuck_service(self):
        return self.services.stuck

    @property
    def circuit_breaker_service(self):
        return self.services.circuit_breaker

    @property
    def telemetry_service(self):
        return self.services.telemetry

    @property
    def observation_service(self):
        return self.services.observation

    @property
    def task_validation_service(self):
        return self.services.task_validation

    def __init__(self, config: ControllerConfig) -> None:
        """Initializes a new instance of the AgentController class."""
        self.config = config

        # --- Service wiring (order matters) ---
        self.services = ControllerServices(self)

        # Rate governor and memory monitor
        self.rate_governor = LLMRateGovernor()
        self.memory_pressure = MemoryPressureMonitor()

        # Initialize core state via lifecycle service
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
        self.services.telemetry.initialize_tool_pipeline()
        self.services.retry.initialize()

    def _register_action_context(
        self, action: Action, ctx: ToolInvocationContext
    ) -> None:
        """Register an invocation context before execution."""
        if hasattr(self, "_action_contexts_by_object"):
            self._action_contexts_by_object[id(action)] = ctx

    def _bind_action_context(self, action: Action, ctx: ToolInvocationContext) -> None:
        """Bind a context to an action's event ID after emission."""
        if not hasattr(self, "_action_contexts_by_event_id"):
            return
        ctx.action_id = action.id
        if ctx.action_id is not None:
            self._action_contexts_by_event_id[ctx.action_id] = ctx
        if hasattr(self, "_action_contexts_by_object"):
            with contextlib.suppress(KeyError):
                self._action_contexts_by_object.pop(id(action))

    def _cleanup_action_context(
        self,
        ctx: ToolInvocationContext,
        *,
        action: Action | None = None,
    ) -> None:
        """Remove context bookkeeping entries."""
        if hasattr(self, "_action_contexts_by_object"):
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
        if hasattr(self, "_action_contexts_by_event_id") and ctx.action_id is not None:
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
                f"{system_message.content[:50]}..."
                if len(system_message.content) > 50
                else system_message.content
            )
            logger.debug("System message: %s", preview)
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
        if set_stop_state:
            await self.set_agent_state_to(AgentState.STOPPED)
        self.state_tracker.close(self.event_stream)
        self.event_stream.unsubscribe(
            EventStreamSubscriber.AGENT_CONTROLLER, self.id or ""
        )
        await self.retry_service.shutdown()
        self._lifecycle = LifecyclePhase.CLOSED

    def log(self, level: str, message: str, extra: dict | None = None) -> None:
        """Logs a message to the agent controller's logger.

        Args:
            level (str): The logging level to use (e.g., 'info', 'debug', 'error').
            message (str): The message to log.
            extra (dict | None, optional): Additional fields to log. Includes session_id by default.

        """
        message = f"[Agent Controller {self.id}] {message}"
        if extra is None:
            extra = {}
        extra_merged = {"session_id": self.id, **extra}
        getattr(logger, level)(message, extra=extra_merged, stacklevel=2)

    async def _react_to_exception(self, e: Exception) -> None:
        """Delegate exception handling to the recovery service."""
        await self.recovery_service.react_to_exception(e)

    def step(self) -> None:
        """Trigger agent to take one step asynchronously.

        Creates async task for step execution with exception handling.
        Keeps a strong reference to prevent GC of the running task.
        """
        self._step_task = asyncio.create_task(self._step_with_exception_handling())

    async def _step_with_exception_handling(self) -> None:
        """Execute agent step with comprehensive exception handling."""
        try:
            await self._step()
        except Exception as e:
            await self.exception_handler.handle_step_exception(e)

    def should_step(self, event: Event) -> bool:
        """Whether the agent should take a step based on an event."""
        return self.step_decision.should_step(event)

    def on_event(self, event: Event) -> None:
        """Callback from the event stream. Notifies the controller of incoming events."""
        run_or_schedule(self._on_event(event))

    def _schedule_coroutine(self, coro: Coroutine[Any, Any, Any]) -> None:
        """Schedule a coroutine using the current or new event loop."""
        run_or_schedule(coro)

    async def _on_event(self, event: Event) -> None:
        """Handle incoming events from the event stream."""
        await self.event_router.route_event(event)

    def _reset(self) -> None:
        """Resets the agent controller."""
        if hasattr(self, "_action_contexts_by_object"):
            self._action_contexts_by_object.clear()
        if hasattr(self, "_action_contexts_by_event_id"):
            self._action_contexts_by_event_id.clear()
        if self._pending_action and hasattr(self._pending_action, "tool_call_metadata"):
            found_observation = any(
                isinstance(event, Observation)
                and event.tool_call_metadata == self._pending_action.tool_call_metadata
                for event in self.state.history
            )
            if not found_observation:
                if self.state.agent_state == AgentState.STOPPED:
                    error_content = ERROR_ACTION_NOT_EXECUTED_STOPPED
                    error_id = ERROR_ACTION_NOT_EXECUTED_STOPPED_ID
                else:
                    error_content = ERROR_ACTION_NOT_EXECUTED_ERROR
                    error_id = ERROR_ACTION_NOT_EXECUTED_ERROR_ID
                obs = ErrorObservation(content=error_content, error_id=error_id)
                if meta := getattr(self._pending_action, "tool_call_metadata", None):
                    obs.tool_call_metadata = meta
                obs.cause = getattr(self._pending_action, "id", None)
                self.event_stream.add_event(obs, EventSource.AGENT)
        self._pending_action = None
        self.agent.reset()

    async def stop(self) -> None:
        """Stop the agent and perform a hard kill on running processes."""
        logger.info("Stopping agent...")
        # 2. Update state to STOPPED
        await self.set_agent_state_to(AgentState.STOPPED)

        # 3. Ensure any pending actions are cleared or marked as cancelled?
        self._pending_action = None

    async def set_agent_state_to(self, new_state: AgentState) -> None:
        """Delegate to the state transition service for consistency."""
        await self.state_service.set_agent_state(new_state)

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
            "debug",
            f"LOCAL STEP {local_step} GLOBAL STEP {global_step}",
            extra={"msg_type": "STEP"},
        )

    async def _step(self) -> None:
        """Execute one agent step.

        Detects stuck agents and enforces iteration and task budget limits.
        When the agent returns a non-blocking action (e.g. AgentThinkAction)
        and has more queued actions from the same LLM response, those are
        drained immediately without re-entering the full polling cycle.
        """
        if not self.step_prerequisites.can_step():
            return

        self._log_step_info()
        self.budget_guard.sync_with_metrics()

        if not await self.step_guard.ensure_can_step():
            return

        if not await self._run_control_flags_safely():
            return

        action = await self.action_execution.get_next_action()
        if action is None:
            return

        # Reset retry count on successful action execution
        # This prevents getting stuck if a previous error has been resolved
        if self.retry_service.retry_count > 0:
            logger.debug(
                "Resetting retry count from %d to 0 after successful execution",
                self.retry_service.retry_count,
            )
            self.retry_service.reset_retry_metrics()

        await self.action_execution.execute_action(action)
        await self._handle_post_execution()

        # Batch-drain queued non-blocking actions from the same LLM response.
        # After a non-runnable action (e.g. AgentThinkAction), no pending_action
        # is set, so we can immediately process the next queued action without
        # waiting for the full polling cycle.
        while self._can_drain_pending():
            action = await self.action_execution.get_next_action()
            if action is None:
                break
            await self.action_execution.execute_action(action)
            await self._handle_post_execution()

    def _can_drain_pending(self) -> bool:
        """Check if we can immediately execute the next queued action.

        Returns True when no action is awaiting its observation (i.e. the last
        action was non-runnable) AND the agent has more queued actions from the
        same LLM response.
        """
        if self._pending_action:
            return False
        pending = getattr(self.agent, "pending_actions", None)
        return bool(pending)

    async def _handle_post_execution(self) -> None:
        """Handle post-execution tasks like rate limits and memory pressure."""
        # Check rate limits after action execution (which likely consumed tokens)
        if hasattr(self.state, "metrics"):
            await self.rate_governor.check_and_wait(
                self.state.metrics.accumulated_token_usage
            )

        # Feed LLM latency for adaptive backoff
        llm_lat = getattr(self.agent, "_last_llm_latency", None)
        if llm_lat and llm_lat > 0:
            self.rate_governor.record_llm_latency(llm_lat)

        # Proactive condensation on memory pressure
        if self.memory_pressure.should_condense():
            level = "CRITICAL" if self.memory_pressure.is_critical() else "WARNING"
            logger.warning(
                "Memory pressure %s (RSS=%.0f MB) — signalling condensation",
                level,
                self.memory_pressure._last_rss_mb,
            )
            self.memory_pressure.record_condensation()
            # Set a metadata flag the orchestrator can check during next step()
            if hasattr(self.state, "turn_signals"):
                self.state.set_memory_pressure(level, source="AgentController")

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
        pending_service = getattr(self, "pending_action_service", None)
        if pending_service:
            return pending_service.get()
        service = getattr(self, "action_service", None)
        if service:
            return service.get_pending_action()
        return None

    @_pending_action.setter
    def _pending_action(self, action: Action | None) -> None:
        pending_service = getattr(self, "pending_action_service", None)
        if pending_service:
            pending_service.set(action)
            return
        service = getattr(self, "action_service", None)
        if service:
            service.set_pending_action(action)

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
            self.id or "",
            state,
            conversation_stats,
            max_iterations,
            max_budget_per_task,
            confirmation_mode,
        )
        self.state_tracker._init_history(self.event_stream)  # type: ignore[attr-defined]  # bootstrap wiring

    def get_trajectory(self, include_screenshots: bool = False) -> list[dict]:
        """Get the complete trajectory of agent actions and observations.

        Must be called after controller is closed.

        Args:
            include_screenshots: Whether to include screenshot data in trajectory

        Returns:
            List of trajectory events as dictionaries

        """
        if self._lifecycle != LifecyclePhase.CLOSED:
            raise RuntimeError(
                f"get_trajectory() requires the controller to be closed. Current phase: {self._lifecycle.value}"
            )
        return self.state_tracker.get_trajectory(include_screenshots)

    def _is_stuck(self) -> bool:
        """Checks if the agent is stuck in a loop.

        Returns:
            bool: True if the agent is stuck, False otherwise.

        """
        return self.stuck_service.is_stuck()

    def __repr__(self) -> str:
        """Get string representation of controller with key state information.

        Returns:
            String representation including ID, agent state, and pending action info

        """
        pending_action_info = "<none>"
        action_service = getattr(self, "action_service", None)
        if action_service:
            info = action_service.get_pending_action_info()
            if info is not None:
                action, timestamp = info
                action_id = getattr(action, "id", "unknown")
                action_type = type(action).__name__
                elapsed_time = time.time() - timestamp
                pending_action_info = (
                    f"{action_type}(id={action_id}, elapsed={elapsed_time:.2f}s)"
                )
        controller_id = getattr(self, "id", "<uninitialized>")
        agent_obj = getattr(self, "agent", "<uninitialized>")
        event_stream = getattr(self, "event_stream", "<uninitialized>")
        state_obj = getattr(self, "state", "<uninitialized>")
        return (
            f"AgentController(id={controller_id}, agent={agent_obj!r}, "
            f"event_stream={event_stream!r}, state={state_obj!r}, "
            f"_pending_action={pending_action_info})"
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
            return self._cached_first_user_message
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

        from backend.validation.task_validator import Task

        return Task(
            description=first_msg.content,
            requirements=[],  # Could be extracted from content
            acceptance_criteria=[],
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
        audit_fn = getattr(self, "_audit_callback", None)
        if audit_fn is None or not callable(audit_fn):
            return
        try:
            task = self._get_initial_task()
            task_name = task.description[:100] if task else "unknown_task"

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
            logger.debug("Audit log failed: %s", e)
