"""Step decision service for SessionOrchestrator.

Centralizes the logic for determining whether the agent should take a step
in response to a given event. Previously inline in SessionOrchestrator.should_step.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.core.interaction_modes import (
    CHAT_MODE,
    PLAN_MODE,
    normalize_interaction_mode,
)
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
    StatusObservation,
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
    - AgentStateChangedObservation, RecallObservation, ErrorObservation, StatusObservation → never step
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
        if bool(getattr(event, 'final_response', False)):
            return False
        if self._is_plain_terminal_agent_message(event):
            return False
        return self._ctrl.get_agent_state() == AgentState.RUNNING

    def _active_interaction_mode(self) -> str:
        state = getattr(self._ctrl, 'state', None)
        extra = getattr(state, 'extra_data', {}) or {}
        if isinstance(extra, dict):
            active_mode = extra.get('active_run_mode')
            if active_mode:
                return normalize_interaction_mode(active_mode)
        agent = getattr(self._ctrl, 'agent', None)
        config = getattr(agent, 'config', None)
        return normalize_interaction_mode(getattr(config, 'mode', 'agent'))

    def _is_plain_terminal_agent_message(self, event: MessageAction) -> bool:
        if event.source != EventSource.AGENT:
            return False
        if not str(getattr(event, 'content', '') or '').strip():
            return False
        if bool(getattr(event, 'wait_for_response', False)):
            return False
        if bool(getattr(event, 'transcript_only', False)):
            return False
        if bool(getattr(event, 'protocol_status', False)):
            return False
        if bool(getattr(event, 'suppress_cli', False)):
            return False
        return self._active_interaction_mode() in {CHAT_MODE, PLAN_MODE}

    def _for_observation(self, event: Observation) -> bool:
        if isinstance(event, NullObservation):
            return bool(event.cause)
        # ErrorObservation is handled by recovery_service (retry or
        # transition to AWAITING_USER_INPUT).  Triggering a step here
        # would bypass retry delays and cause infinite retry loops.
        return not isinstance(
            event,
            AgentStateChangedObservation
            | RecallObservation
            | ErrorObservation
            | StatusObservation,
        )
