from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from backend.core.logging.logger import app_logger as logger
from backend.core.schemas import AgentState
from backend.ledger import EventSource
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
            AgentState.STOPPED,
            AgentState.FINISHED,
            AgentState.ERROR,
            AgentState.RATE_LIMITED,
            AgentState.AWAITING_USER_INPUT,
            AgentState.AWAITING_USER_CONFIRMATION,
            AgentState.REJECTED,
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
            AgentState.RUNNING,
            AgentState.AWAITING_USER_INPUT,
            AgentState.STOPPED,
            AgentState.ERROR,
        }
    ),
    AgentState.RATE_LIMITED: frozenset(
        {
            AgentState.RUNNING,
            AgentState.STOPPED,
            AgentState.ERROR,
            AgentState.AWAITING_USER_INPUT,
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

        from backend.core.logging.session_event_logger import emit_session_event

        emit_session_event(
            'STATE_CHANGE',
            {
                'from': old_state.value,
                'to': new_state.value,
                'agent': self._context.controller_name,
            },
        )

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

        await self._handle_state_reset(new_state)
        self._handle_error_recovery(old_state, new_state)
        self._handle_watchdog_lifecycle(old_state, new_state)
        self._refresh_session_log_audit(old_state, new_state)

        reason = self._context.state.last_error if new_state == AgentState.ERROR else ''
        self._context.event_stream.add_event(
            AgentStateChangedObservation('', self._context.state.agent_state, reason),
            EventSource.ENVIRONMENT,
        )
        self._context.save_state()

    @staticmethod
    def _refresh_session_log_audit(
        old_state: AgentState, new_state: AgentState
    ) -> None:
        """Refresh session audit artifacts off the latency-sensitive state path."""
        if old_state != AgentState.RUNNING:
            return
        if new_state not in (
            AgentState.STOPPED,
            AgentState.ERROR,
            AgentState.FINISHED,
            AgentState.AWAITING_USER_INPUT,
            AgentState.RATE_LIMITED,
        ):
            return
        try:
            from backend.core.logging.logger import finalize_session_logging_audit
            from backend.utils.async_helpers.async_utils import create_tracked_task

            create_tracked_task(
                asyncio.to_thread(finalize_session_logging_audit),
                name='session-log-audit-refresh',
            )
        except Exception:
            logger.debug('Session log audit refresh scheduling failed', exc_info=True)

    def _handle_watchdog_lifecycle(
        self, old_state: AgentState, new_state: AgentState
    ) -> None:
        """Start/stop the independent watchdog based on state transitions.

        The watchdog is only meaningful while the agent is in RUNNING state.
        Starting it on entry and stopping it on exit avoids spurious stall
        detections during user input or terminal states.
        """
        try:
            controller = self._context.get_controller()
        except (AttributeError, TypeError):
            return
        start_watchdog = getattr(controller, '_start_watchdog', None)
        stop_watchdog = getattr(controller, '_stop_watchdog', None)

        if new_state == AgentState.RUNNING:
            if callable(start_watchdog):
                try:
                    start_watchdog()
                except Exception:
                    pass
            retry_service = getattr(controller, 'retry_service', None)
            ensure_worker = getattr(retry_service, 'ensure_worker_started', None)
            if callable(ensure_worker):
                try:
                    ensure_worker()
                except Exception:
                    pass
        elif (
            old_state == AgentState.RUNNING
            and new_state != AgentState.RUNNING
            and callable(stop_watchdog)
        ):
            try:
                stop_watchdog()
            except Exception:
                pass

    async def _handle_state_reset(self, new_state: AgentState) -> None:
        if new_state in (AgentState.STOPPED, AgentState.ERROR):
            await self._context.reset_controller()

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

        if (
            old_state == AgentState.AWAITING_USER_INPUT
            and new_state == AgentState.RUNNING
        ):
            circuit_breaker_service = getattr(
                self._context.get_controller(), 'circuit_breaker_service', None
            )
            circuit_breaker = (
                getattr(circuit_breaker_service, 'circuit_breaker', None)
                if circuit_breaker_service
                else None
            )
            if circuit_breaker is not None and hasattr(
                circuit_breaker, 'reset_task_counters'
            ):
                circuit_breaker.reset_task_counters()
