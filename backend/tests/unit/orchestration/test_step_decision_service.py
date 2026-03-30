"""Unit tests for backend.orchestration.services.step_decision_service."""

from __future__ import annotations

from unittest.mock import MagicMock


from backend.orchestration.services.step_decision_service import StepDecisionService
from backend.core.schemas import AgentState
from backend.ledger import EventSource
from backend.ledger.action import MessageAction
from backend.ledger.action.agent import CondensationAction, CondensationRequestAction
from backend.ledger.observation import AgentStateChangedObservation, NullObservation
from backend.ledger.observation.agent import RecallObservation


def _make_ctrl(agent_state: AgentState = AgentState.RUNNING):
    ctrl = MagicMock()
    ctrl.get_agent_state.return_value = agent_state
    return ctrl


class TestStepDecisionService:
    # ── User message actions ───────────────────────────────────────

    def test_user_message_always_steps(self):
        svc = StepDecisionService(_make_ctrl())
        action = MessageAction(content="hello")
        action.source = EventSource.USER
        assert svc.should_step(action) is True

    def test_user_message_steps_even_when_awaiting_input(self):
        svc = StepDecisionService(_make_ctrl(AgentState.AWAITING_USER_INPUT))
        action = MessageAction(content="hello")
        action.source = EventSource.USER
        assert svc.should_step(action) is True

    # ── Agent message actions ──────────────────────────────────────

    def test_agent_message_steps_when_running(self):
        svc = StepDecisionService(_make_ctrl(AgentState.RUNNING))
        action = MessageAction(content="thinking")
        action.source = EventSource.AGENT
        assert svc.should_step(action) is True

    def test_agent_message_no_step_when_awaiting_input(self):
        svc = StepDecisionService(_make_ctrl(AgentState.AWAITING_USER_INPUT))
        action = MessageAction(content="thinking")
        action.source = EventSource.AGENT
        assert svc.should_step(action) is False

    # ── Condensation actions ───────────────────────────────────────

    def test_condensation_action_steps(self):
        svc = StepDecisionService(_make_ctrl())
        action = CondensationAction(pruned_event_ids=[1, 2])
        assert svc.should_step(action) is True

    def test_condensation_request_steps(self):
        svc = StepDecisionService(_make_ctrl())
        action = CondensationRequestAction()
        assert svc.should_step(action) is True

    # ── Observations ───────────────────────────────────────────────

    def test_null_observation_without_cause_no_step(self):
        svc = StepDecisionService(_make_ctrl())
        obs = NullObservation(content="")
        obs.cause = 0  # falsy
        assert svc.should_step(obs) is False

    def test_null_observation_with_cause_steps(self):
        svc = StepDecisionService(_make_ctrl())
        obs = NullObservation(content="")
        obs.cause = 42
        assert svc.should_step(obs) is True

    def test_agent_state_changed_never_steps(self):
        svc = StepDecisionService(_make_ctrl())
        obs = AgentStateChangedObservation(
            content="", agent_state=AgentState.RUNNING, reason=""
        )
        assert svc.should_step(obs) is False

    def test_recall_observation_never_steps(self):
        svc = StepDecisionService(_make_ctrl())
        from backend.core.enums import RecallType

        obs = RecallObservation(content="", recall_type=RecallType.WORKSPACE_CONTEXT)
        assert svc.should_step(obs) is False

    def test_generic_observation_steps(self):
        """Non-special observations should trigger a step."""
        from backend.ledger.observation import ErrorObservation

        svc = StepDecisionService(_make_ctrl())
        obs = ErrorObservation(content="fail")
        assert svc.should_step(obs) is True

    # ── Non-event types ────────────────────────────────────────────

    def test_random_object_no_step(self):
        svc = StepDecisionService(_make_ctrl())
        assert svc.should_step(object()) is False  # type: ignore[arg-type]
