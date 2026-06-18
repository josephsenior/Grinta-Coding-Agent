"""_SessionOrchestratorStateMixin mixin for SessionOrchestrator.

Pure code motion: extracted from
``backend/orchestration/session_orchestrator.py`` to break the file past the
40 KB cap. Methods here are bound to ``_SessionOrchestratorStateMixin`` and mixed into
``SessionOrchestrator`` via its MRO.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

from backend.core.enums import LifecyclePhase
from backend.core.logger import app_logger as logger
from backend.core.schemas import AgentState
from backend.ledger import EventSource
from backend.ledger.action import (
    Action,
    ActionConfirmationStatus,
    MessageAction,
)
from backend.ledger.observation import (
    AgentStateChangedObservation,
)
from backend.orchestration.state.state import State

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
    from backend.core.enums import AgentState, LifecyclePhase
    from backend.ledger.action import MessageAction
    from backend.ledger.event import Event, EventSource
    from backend.ledger.observation import AgentStateChangedObservation
    from backend.orchestration.telemetry.conversation_stats import ConversationStats
    from backend.orchestration.state.state import State


class _SessionOrchestratorStateMixin:
    """Mixin: agent state, transcript, repr, audit logging, is_stuck checks."""

    async def set_agent_state_to(self, new_state: AgentState) -> None:
        """Delegate to the state transition service for consistency."""
        await self.services.state.set_agent_state(new_state)

    async def apply_user_decision(self, approved: bool) -> None:
        """Apply the user's decision to the currently-pending action.

        This is a direct method call (not an event) so the decision is
        applied atomically: the pending action's ``confirmation_state``
        is set, the pending slot is cleared, the action is re-emitted
        (so the agent loop picks it up), and the agent state transitions
        out of ``AWAITING_USER_CONFIRMATION`` in one synchronous sequence.

        Replacing the previous ``ChangeAgentStateAction(USER_CONFIRMED/REJECTED)``
        event flow eliminates the race where the user decision arrived
        while the agent was still in ``AWAITING_USER_CONFIRMATION`` (the
        event's transition ``running → user_confirmed`` was rejected by
        the state machine).
        """
        pending = self.services.pending_action.get()
        if pending is None:
            current_state = self.get_agent_state()
            if current_state == AgentState.AWAITING_USER_CONFIRMATION:
                logger.warning(
                    'apply_user_decision: no pending action; releasing stale confirmation gate'
                )
                new_state = (
                    AgentState.RUNNING if approved else AgentState.AWAITING_USER_INPUT
                )
                await self.set_agent_state_to(new_state)
            else:
                logger.warning(
                    'apply_user_decision: no pending action (state=%s); ignoring.',
                    current_state,
                )
            return

        if hasattr(pending, 'thought'):
            pending.thought = ''
        # Clear the pre-confirmation stream row while ``_id`` is still valid.
        # Wiping ``_id`` first made ``clear_for_action`` a no-op and left stale
        # outstanding rows that timed out ~120s later as false FileEditAction
        # pending timeouts during auto-confirm soak runs.
        self.services.pending_action.clear_for_action(pending)
        pending._id = None
        pending.confirmation_state = (
            ActionConfirmationStatus.CONFIRMED
            if approved
            else ActionConfirmationStatus.REJECTED
        )

        new_state = AgentState.RUNNING if approved else AgentState.AWAITING_USER_INPUT
        await self.set_agent_state_to(new_state)

        self.services.context.emit_event(pending, EventSource.AGENT)

        self.step()

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
    ) -> None:
        """Set the initial state for the agent controller.

        Args:
            state: Initial state object (None for new conversations)

            conversation_stats: Statistics tracker for the conversation

            max_iterations: Maximum number of agent iterations allowed

            max_budget_per_task: Maximum budget in USD per task



        """
        self.state_tracker.set_initial_state(
            self.id or '',
            state,
            conversation_stats,
            max_iterations,
            max_budget_per_task,
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
