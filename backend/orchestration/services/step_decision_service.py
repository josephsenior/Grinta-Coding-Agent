"""Step decision service for SessionOrchestrator.

Centralizes the logic for determining whether the agent should take a step
in response to a given event. Previously inline in SessionOrchestrator.should_step.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.core.schemas import AgentState
from backend.ledger import EventSource
from backend.ledger.action import (
    Action,
    MessageAction,
)
from backend.ledger.action.agent import (
    CondensationAction,
    CondensationRequestAction,
)
from backend.ledger.observation import (
    AgentStateChangedObservation,
    ErrorObservation,
    NullObservation,
    Observation,
)
from backend.ledger.observation.agent import RecallObservation

if TYPE_CHECKING:
    from backend.ledger.event import Event
    from backend.orchestration.session_orchestrator import SessionOrchestrator


class StepDecisionService:
    """Determines whether an event should trigger an agent step.

    Rules:
    - User messages → always step
    - Agent messages → step unless waiting for user input
    - Condensation actions → always step
    - NullObservation → step only when it has a cause
    - AgentStateChangedObservation, RecallObservation, ErrorObservation → never step
    - All other observations → step
    """

    def __init__(self, controller: SessionOrchestrator) -> None:
        self._ctrl = controller

    def should_step(self, event: Event) -> bool:
        """Whether the agent should take a step based on an event."""
        if isinstance(event, Action):
            return self._for_action(event)
        if isinstance(event, Observation):
            return self._for_observation(event)
        return False

    # ── private ───────────────────────────────────────────────────────

    def _for_action(self, event: Action) -> bool:
        if isinstance(event, MessageAction):
            return self._for_message_action(event)
        if isinstance(event, CondensationAction):
            return True
        return isinstance(event, CondensationRequestAction)

    def _for_message_action(self, event: MessageAction) -> bool:
        if event.source == EventSource.USER:
            return True
        return self._ctrl.get_agent_state() != AgentState.AWAITING_USER_INPUT

    def _for_observation(self, event: Observation) -> bool:
        if isinstance(event, NullObservation):
            return bool(event.cause)
        # ErrorObservation is handled by recovery_service (retry or
        # transition to AWAITING_USER_INPUT).  Triggering a step here
        # would bypass retry delays and cause infinite retry loops.
        return not isinstance(
            event, AgentStateChangedObservation | RecallObservation | ErrorObservation
        )
