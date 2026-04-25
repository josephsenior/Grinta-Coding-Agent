from __future__ import annotations

from typing import TYPE_CHECKING

from backend.core.logger import app_logger as logger
from backend.core.schemas import AgentState
from backend.ledger import EventSource
from backend.ledger.action import ActionConfirmationStatus
from backend.ledger.observation import AgentStateChangedObservation

if TYPE_CHECKING:
    from backend.orchestration.services.orchestration_context import (
        OrchestrationContext,
    )


# ── Valid state transitions ─────────────────────────────────────────────
# Maps ``from_state`` → frozenset of valid ``to_state`` values.
# Any transition NOT listed here is **rejected** with a warning.
VALID_TRANSITIONS: dict[AgentState, frozenset[AgentState]] = {
    AgentState.LOADING: frozenset(
        {
            AgentState.RUNNING,
            AgentState.AWAITING_USER_INPUT,
            AgentState.ERROR,
            AgentState.STOPPED,
        }
    ),
    AgentState.RUNNING: frozenset(
        {
            AgentState.PAUSED,
            AgentState.STOPPED,
            AgentState.FINISHED,
            AgentState.ERROR,
            AgentState.RATE_LIMITED,
            AgentState.AWAITING_USER_INPUT,
            AgentState.AWAITING_USER_CONFIRMATION,
            AgentState.REJECTED,
        }
    ),
    AgentState.PAUSED: frozenset(
        {
            AgentState.RUNNING,
            AgentState.STOPPED,
            AgentState.ERROR,
        }
    ),
    AgentState.STOPPED: frozenset(
        {
            AgentState.LOADING,
            AgentState.RUNNING,
            # The agent may complete a long LLM call while the controller was
            # stopped (e.g. a timing race after a user-stop or step timeout).
            # Allow it to surface its reply rather than crashing on the
            # transition and silently losing the message.
            AgentState.AWAITING_USER_INPUT,
        }
    ),
    AgentState.FINISHED: frozenset(
        {
            AgentState.RUNNING,
            AgentState.LOADING,
            AgentState.STOPPED,
        }
    ),
    AgentState.REJECTED: frozenset(
        {
            AgentState.RUNNING,
            AgentState.STOPPED,
            AgentState.ERROR,
        }
    ),
    AgentState.ERROR: frozenset(
        {
            AgentState.RUNNING,
            AgentState.LOADING,
            AgentState.STOPPED,
        }
    ),
    AgentState.AWAITING_USER_INPUT: frozenset(
        {
            AgentState.RUNNING,
            AgentState.STOPPED,
            AgentState.ERROR,
        }
    ),
    AgentState.AWAITING_USER_CONFIRMATION: frozenset(
        {
            AgentState.USER_CONFIRMED,
            AgentState.USER_REJECTED,
            AgentState.RUNNING,
            AgentState.STOPPED,
            AgentState.ERROR,
        }
    ),
    AgentState.USER_CONFIRMED: frozenset(
        {
            AgentState.RUNNING,
            AgentState.STOPPED,
            AgentState.ERROR,
        }
    ),
    AgentState.USER_REJECTED: frozenset(
        {
            AgentState.RUNNING,
            AgentState.STOPPED,
            AgentState.ERROR,
            AgentState.REJECTED,
        }
    ),
    AgentState.RATE_LIMITED: frozenset(
        {
            AgentState.RUNNING,
            AgentState.STOPPED,
            AgentState.ERROR,
        }
    ),
}


class InvalidStateTransitionError(RuntimeError):
    """Raised when a state transition violates the allowed transition graph."""

    def __init__(self, old: AgentState, new: AgentState, agent_name: str) -> None:
        self.old_state = old
        self.new_state = new
        super().__init__(
            f"Invalid state transition {old.value} → {new.value} for agent '{agent_name}'"
        )


class StateTransitionService:
    """Owns agent state transitions and related side effects."""

    def __init__(self, context: OrchestrationContext) -> None:
        self._context = context

    async def set_agent_state(self, new_state: AgentState) -> None:
        old_state = self._context.state.agent_state
        logger.info(
            'Setting agent(%s) state from %s to %s',
            self._context.controller_name,
            old_state,
            new_state,
        )

        if new_state == old_state:
            return

        # ── Transition validation ──────────────────────────────────────
        allowed = VALID_TRANSITIONS.get(old_state)
        if allowed is not None and new_state not in allowed:
            logger.warning(
                'Rejected state transition %s → %s for agent %s.',
                old_state,
                new_state,
                self._context.controller_name,
            )
            raise InvalidStateTransitionError(
                old_state,
                new_state,
                self._context.controller_name,
            )

        self._context.state.set_agent_state(
            new_state,
            source='StateTransitionService.set_agent_state',
        )

        self._handle_state_reset(new_state)
        self._handle_error_recovery(old_state, new_state)
        self._handle_pending_action_confirmation(new_state)

        reason = self._context.state.last_error if new_state == AgentState.ERROR else ''
        self._context.event_stream.add_event(
            AgentStateChangedObservation('', self._context.state.agent_state, reason),
            EventSource.ENVIRONMENT,
        )
        self._context.save_state()

    def _handle_state_reset(self, new_state: AgentState) -> None:
        if new_state in (AgentState.STOPPED, AgentState.ERROR):
            self._context.reset_controller()

    def _handle_error_recovery(
        self, old_state: AgentState, new_state: AgentState
    ) -> None:
        state_tracker = self._context.state_tracker
        if (
            state_tracker
            and old_state == AgentState.ERROR
            and new_state == AgentState.RUNNING
        ):
            state_tracker.maybe_increase_control_flags_limits(
                self._context.headless_mode
            )

    def _handle_pending_action_confirmation(self, new_state: AgentState) -> None:
        pending_action = self._context.pending_action
        if pending_action is None or new_state not in (
            AgentState.USER_CONFIRMED,
            AgentState.USER_REJECTED,
        ):
            return

        if hasattr(pending_action, 'thought'):
            pending_action.thought = ''

        pending_action.confirmation_state = (
            ActionConfirmationStatus.CONFIRMED
            if new_state == AgentState.USER_CONFIRMED
            else ActionConfirmationStatus.REJECTED
        )
        pending_action._id = None
        self._context.emit_event(pending_action, EventSource.AGENT)
        self._context.clear_pending_action()
