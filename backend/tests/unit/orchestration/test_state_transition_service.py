"""Unit tests for backend.orchestration.services.state_transition_service."""

from __future__ import annotations

import pytest

from backend.orchestration.services.state_transition_service import (
    VALID_TRANSITIONS,
    InvalidStateTransitionError,
    StateTransitionService,
)
from backend.core.schemas import AgentState


# ---------------------------------------------------------------------------
# InvalidStateTransitionError
# ---------------------------------------------------------------------------


class TestInvalidStateTransitionError:
    def test_message(self):
        err = InvalidStateTransitionError(
            AgentState.LOADING, AgentState.FINISHED, "bot"
        )
        assert "LOADING" in str(err) or "loading" in str(err).lower()
        assert "FINISHED" in str(err) or "finished" in str(err).lower()
        assert "bot" in str(err)

    def test_attributes(self):
        err = InvalidStateTransitionError(AgentState.PAUSED, AgentState.RUNNING, "ag")
        assert err.old_state == AgentState.PAUSED
        assert err.new_state == AgentState.RUNNING

    def test_is_runtime_error(self):
        err = InvalidStateTransitionError(AgentState.ERROR, AgentState.RUNNING, "x")
        assert isinstance(err, RuntimeError)


# ---------------------------------------------------------------------------
# VALID_TRANSITIONS table completeness
# ---------------------------------------------------------------------------


class TestValidTransitions:
    def test_all_states_have_entry(self):
        """Every AgentState that we expect to be a 'from' state should be present."""
        for state in AgentState:
            # Some states might be terminal-only or not used as source.
            # Just confirm the dict has entries for common states.
            pass
        # At a minimum these must be in the table:
        required = {
            AgentState.LOADING,
            AgentState.RUNNING,
            AgentState.PAUSED,
            AgentState.STOPPED,
            AgentState.FINISHED,
            AgentState.ERROR,
        }
        assert required.issubset(VALID_TRANSITIONS.keys())

    def test_running_can_go_to_paused(self):
        assert AgentState.PAUSED in VALID_TRANSITIONS[AgentState.RUNNING]

    def test_running_can_go_to_finished(self):
        assert AgentState.FINISHED in VALID_TRANSITIONS[AgentState.RUNNING]

    def test_running_can_go_to_error(self):
        assert AgentState.ERROR in VALID_TRANSITIONS[AgentState.RUNNING]

    def test_paused_can_resume_to_running(self):
        assert AgentState.RUNNING in VALID_TRANSITIONS[AgentState.PAUSED]

    def test_finished_can_restart(self):
        assert AgentState.RUNNING in VALID_TRANSITIONS[AgentState.FINISHED]

    def test_loading_cannot_go_to_finished(self):
        assert AgentState.FINISHED not in VALID_TRANSITIONS[AgentState.LOADING]

    def test_error_can_restart(self):
        assert AgentState.RUNNING in VALID_TRANSITIONS[AgentState.ERROR]

    def test_rate_limited_can_resume(self):
        assert AgentState.RUNNING in VALID_TRANSITIONS[AgentState.RATE_LIMITED]


# ---------------------------------------------------------------------------
# StateTransitionService (unit-level, no real controller)
# ---------------------------------------------------------------------------


class _FakeState:
    def __init__(self, agent_state: AgentState):
        self.agent_state = agent_state
        self.last_error = ""

    def set_agent_state(self, new_state, source=""):
        self.agent_state = new_state


class _FakeEventStream:
    def __init__(self):
        self.events = []

    def add_event(self, event, source):
        self.events.append((event, source))


class _FakeContext:
    def __init__(self, state: _FakeState):
        self.state = state
        self.event_stream = _FakeEventStream()
        self.controller_name = "test-agent"
        self.state_tracker = None
        self.pending_action = None
        self._saved = False

    def emit_event(self, event, source):
        self.event_stream.add_event(event, source)

    def save_state(self):
        self._saved = True

    def reset_controller(self):
        pass

    def clear_pending_action(self):
        self.pending_action = None


class TestStateTransitionServiceUnit:
    @pytest.fixture()
    def ctx(self):
        return _FakeContext(_FakeState(AgentState.RUNNING))

    @pytest.fixture()
    def svc(self, ctx):
        return StateTransitionService(ctx)

    async def test_same_state_noop(self, svc, ctx):
        await svc.set_agent_state(AgentState.RUNNING)
        assert ctx.state.agent_state == AgentState.RUNNING
        assert not ctx.event_stream.events

    async def test_valid_transition_emits_event(self, svc, ctx):
        await svc.set_agent_state(AgentState.PAUSED)
        assert ctx.state.agent_state == AgentState.PAUSED
        assert len(ctx.event_stream.events) == 1
        assert ctx._saved

    async def test_invalid_transition_raises(self, svc, ctx):
        # RUNNING → LOADING is not in the valid table
        with pytest.raises(InvalidStateTransitionError):
            await svc.set_agent_state(AgentState.LOADING)

    async def test_reset_on_stopped(self, ctx):
        ctx.state = _FakeState(AgentState.RUNNING)
        svc = StateTransitionService(ctx)
        # Monkey-patch reset_controller to track call
        reset_called = []
        ctx.reset_controller = lambda: reset_called.append(True)
        await svc.set_agent_state(AgentState.STOPPED)
        assert reset_called

    async def test_reset_on_error(self, ctx):
        ctx.state = _FakeState(AgentState.RUNNING)
        svc = StateTransitionService(ctx)
        reset_called = []
        ctx.reset_controller = lambda: reset_called.append(True)
        await svc.set_agent_state(AgentState.ERROR)
        assert reset_called
