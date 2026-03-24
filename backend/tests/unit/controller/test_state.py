"""Unit tests for backend.controller.state.state — State dataclass."""

from __future__ import annotations

import json
from typing import Any, cast

import pytest

from backend.controller.state.state import (
    RESUMABLE_STATES,
    STATE_SCHEMA_VERSION,
    State,
    TrafficControlState,
)
from backend.core.schemas import AgentState
from backend.events.event import Event


# ---------------------------------------------------------------------------
# TrafficControlState constants
# ---------------------------------------------------------------------------


class TestTrafficControlState:
    def test_values(self):
        assert TrafficControlState.NORMAL == "normal"
        assert TrafficControlState.THROTTLING == "throttling"
        assert TrafficControlState.PAUSED == "paused"


# ---------------------------------------------------------------------------
# RESUMABLE_STATES
# ---------------------------------------------------------------------------


class TestResumableStates:
    def test_contains_running(self):
        assert AgentState.RUNNING in RESUMABLE_STATES

    def test_contains_paused(self):
        assert AgentState.PAUSED in RESUMABLE_STATES

    def test_contains_finished(self):
        assert AgentState.FINISHED in RESUMABLE_STATES

    def test_error_not_resumable(self):
        assert AgentState.ERROR not in RESUMABLE_STATES


# ---------------------------------------------------------------------------
# State — mutation methods
# ---------------------------------------------------------------------------


class TestStateMutations:
    def test_set_last_error(self):
        s = State()
        s.set_last_error("boom", source="test")
        assert s.last_error == "boom"

    def test_set_outputs(self):
        s = State()
        s.set_outputs({"a": 1}, source="test")
        assert s.outputs == {"a": 1}

    def test_set_extra(self):
        s = State()
        s.set_extra("key", "val", source="test")
        assert s.extra_data["key"] == "val"

    def test_adjust_iteration_limit(self):
        s = State()
        s.adjust_iteration_limit(200, source="test")
        assert s.iteration_flag.max_value == 200

    def test_set_agent_state(self):
        s = State()
        s.set_agent_state(AgentState.RUNNING, source="test")
        assert s.agent_state == AgentState.RUNNING


# ---------------------------------------------------------------------------
# State — JSON round-trip
# ---------------------------------------------------------------------------


class TestStateJsonRoundTrip:
    def test_roundtrip_basic(self):
        s = State(session_id="sess-1", user_id="user-1")
        s.set_agent_state(AgentState.RUNNING, source="test")
        s.set_last_error("err")
        s.set_outputs({"x": 42})
        s.set_extra("tag", "v1")
        s.confirmation_mode = True

        raw = s._to_json_str()
        doc = json.loads(raw)
        assert doc["_schema_version"] == STATE_SCHEMA_VERSION
        assert doc["session_id"] == "sess-1"
        assert doc["agent_state"] == AgentState.RUNNING.value

        restored = State._from_json_str(raw)
        assert restored.session_id == "sess-1"
        assert restored.agent_state == AgentState.RUNNING
        assert restored.last_error == "err"
        assert restored.outputs == {"x": 42}
        assert restored.extra_data["tag"] == "v1"
        assert restored.confirmation_mode is True

    def test_from_raw_rejects_non_json(self):
        with pytest.raises(ValueError, match="legacy pickle"):
            State._from_raw("base64garbagedata==")

    def test_from_json_rejects_wrong_version(self):
        raw = json.dumps({"_schema_version": 0})
        with pytest.raises(ValueError, match="Unknown state schema version"):
            State._from_json_str(raw)

    def test_iteration_flag_roundtrip(self):
        s = State()
        s.iteration_flag.current_value = 42
        s.iteration_flag.max_value = 200

        restored = State._from_json_str(s._to_json_str())
        assert restored.iteration_flag.current_value == 42
        assert restored.iteration_flag.max_value == 200

    def test_budget_flag_roundtrip(self):
        from backend.controller.state.control_flags import BudgetControlFlag

        s = State()
        s.budget_flag = BudgetControlFlag(
            limit_increase_amount=0.5,
            current_value=0.1,
            max_value=1.0,
        )
        restored = State._from_json_str(s._to_json_str())
        assert restored.budget_flag is not None
        assert restored.budget_flag.current_value == pytest.approx(0.1)

    def test_metrics_roundtrip(self):
        from backend.llm.metrics import Metrics

        s = State()
        s.metrics = Metrics()
        raw = s._to_json_str()
        restored = State._from_json_str(raw)
        assert restored.metrics is not None

    def test_resume_state_roundtrip(self):
        s = State()
        s.set_agent_state(AgentState.PAUSED, source="test")
        s.resume_state = AgentState.RUNNING
        restored = State._from_json_str(s._to_json_str())
        assert restored.resume_state == AgentState.RUNNING

    def test_turn_signals_repetition_score_roundtrip(self):
        s = State()
        s.turn_signals.planning_directive = "verify state"
        s.turn_signals.memory_pressure = "high"
        s.turn_signals.repetition_score = 0.75

        restored = State._from_json_str(s._to_json_str())

        assert restored.turn_signals.planning_directive == "verify state"
        assert restored.turn_signals.memory_pressure == "high"
        assert restored.turn_signals.repetition_score == pytest.approx(0.75)


# ---------------------------------------------------------------------------
# State — __getstate__ / __setstate__
# ---------------------------------------------------------------------------


class TestStatePickle:
    def test_getstate_excludes_history(self):
        s = State()
        s.history = cast(list[Event], ["a", "b"])
        d: dict[str, Any] = s.__getstate__()
        assert d["history"] == []

    def test_setstate_defaults(self):
        s = State()
        d: dict[str, Any] = {}
        s.__setstate__(d)
        assert s.history == []
        assert s.iteration_flag is not None


# ---------------------------------------------------------------------------
# State — get_current_user_intent, get_last_*_message
# ---------------------------------------------------------------------------


class TestStateViewHelpers:
    def test_get_last_agent_message_none(self):
        s = State()
        s.history = []
        assert s.get_last_agent_message() is None

    def test_get_last_user_message_none(self):
        s = State()
        s.history = []
        assert s.get_last_user_message() is None

    def test_get_current_user_intent_empty(self):
        s = State()
        s.history = []
        result = s.get_current_user_intent()
        assert result == (None, [])

    def test_to_llm_metadata(self):
        s = State(session_id="s1", user_id="u1")
        md = s.to_llm_metadata("gpt-4", "agent-1")
        assert md["session_id"] == "s1"
        assert any("gpt-4" in t for t in md["tags"])

    def test_get_local_step_no_parent(self):
        s = State()
        s.iteration_flag.current_value = 10
        s.parent_iteration = 0
        assert s.get_local_step() == 10

    def test_get_local_step_with_parent(self):
        s = State()
        s.iteration_flag.current_value = 15
        s.parent_iteration = 10
        assert s.get_local_step() == 5
