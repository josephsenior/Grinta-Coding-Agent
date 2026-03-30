"""Unit tests for backend.orchestration.state.state_tracker."""

from __future__ import annotations

from unittest.mock import MagicMock

from backend.orchestration.state.state import State
from backend.orchestration.state.state_tracker import MAX_HISTORY_EVENTS, StateTracker
from backend.ledger.action import MessageAction
from backend.ledger.action.empty import NullAction
from backend.ledger.observation.empty import NullObservation


class TestStateTrackerInitHistory:
    def test_init_history_uses_persisted_range(self):
        tracker = StateTracker(sid="sid-1", file_store=None, user_id="user-1")
        tracker.state = State(start_id=5, end_id=8)
        event_stream = MagicMock()
        event_stream.search_events.return_value = ["e1", "e2"]

        tracker._init_history(event_stream)

        assert tracker.state.start_id == 5
        assert tracker.state.history == ["e1", "e2"]
        event_stream.search_events.assert_called_once()
        kwargs = event_stream.search_events.call_args.kwargs
        assert kwargs["start_id"] == 5
        assert kwargs["end_id"] == 8
        assert kwargs["reverse"] is False

    def test_init_history_invalid_range_clears_history(self):
        tracker = StateTracker(sid="sid-1", file_store=None, user_id="user-1")
        tracker.state = State(start_id=9, end_id=3)
        tracker.state.history = [MessageAction(content="stale")]
        event_stream = MagicMock()

        tracker._init_history(event_stream)

        assert tracker.state.history == []
        event_stream.search_events.assert_not_called()


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestStateTrackerInit:
    def test_basic_init(self):
        st = StateTracker(sid="s1", file_store=None, user_id="u1")
        assert st.sid == "s1"
        assert st.user_id == "u1"

    def test_set_initial_state_new(self):
        st = StateTracker(sid="s1", file_store=None, user_id=None)
        stats = MagicMock()
        st.set_initial_state(
            session_id="s1",
            state=None,
            conversation_stats=stats,
            max_iterations=200,
            max_budget_per_task=5.0,
            confirmation_mode=True,
        )
        assert st.state.session_id == "s1"
        assert st.state.iteration_flag.max_value == 200
        assert st.state.budget_flag is not None
        assert st.state.budget_flag.max_value == 5.0
        assert st.state.confirmation_mode is True
        assert st.state.start_id == 0

    def test_set_initial_state_existing(self):
        st = StateTracker(sid="s1", file_store=None, user_id=None)
        existing = State(session_id="old")
        existing.start_id = 10
        stats = MagicMock()
        st.set_initial_state(
            session_id="s1",
            state=existing,
            conversation_stats=stats,
            max_iterations=100,
            max_budget_per_task=None,
        )
        assert st.state.session_id == "old"
        assert st.state.start_id == 10

    def test_set_initial_state_fixes_negative_start_id(self):
        st = StateTracker(sid="s1", file_store=None, user_id=None)
        existing = State()
        existing.start_id = -1
        st.set_initial_state(
            session_id="s1",
            state=existing,
            conversation_stats=MagicMock(),
            max_iterations=100,
            max_budget_per_task=None,
        )
        assert st.state.start_id == 0


# ---------------------------------------------------------------------------
# History filter
# ---------------------------------------------------------------------------


class TestStateTrackerHistoryFilter:
    def test_message_action_included(self):
        st = StateTracker(sid="s", file_store=None, user_id=None)
        action = MessageAction(content="hi")
        assert st.agent_history_filter.include(action) is True

    def test_null_action_excluded(self):
        st = StateTracker(sid="s", file_store=None, user_id=None)
        action = NullAction()
        assert st.agent_history_filter.include(action) is False

    def test_null_observation_excluded(self):
        st = StateTracker(sid="s", file_store=None, user_id=None)
        obs = NullObservation(content="")
        assert st.agent_history_filter.include(obs) is False


# ---------------------------------------------------------------------------
# add_history + trimming
# ---------------------------------------------------------------------------


class TestStateTrackerAddHistory:
    def test_add_event(self):
        st = StateTracker(sid="s", file_store=None, user_id=None)
        st.set_initial_state(
            session_id="s",
            state=None,
            conversation_stats=MagicMock(),
            max_iterations=100,
            max_budget_per_task=None,
        )
        action = MessageAction(content="hello")
        st.add_history(action)
        assert len(st.state.history) == 1

    def test_excluded_events_not_added(self):
        st = StateTracker(sid="s", file_store=None, user_id=None)
        st.set_initial_state(
            session_id="s",
            state=None,
            conversation_stats=MagicMock(),
            max_iterations=100,
            max_budget_per_task=None,
        )
        st.add_history(NullAction())
        assert not st.state.history

    def test_trim_on_count_overflow(self):
        st = StateTracker(sid="s", file_store=None, user_id=None)
        st.set_initial_state(
            session_id="s",
            state=None,
            conversation_stats=MagicMock(),
            max_iterations=100,
            max_budget_per_task=None,
        )
        # Stuff history just above the cap (use int placeholders for overflow test)
        st.state.history = list(range(MAX_HISTORY_EVENTS + 10))  # type: ignore[arg-type]
        st._maybe_trim_history()
        assert len(st.state.history) < MAX_HISTORY_EVENTS + 10


# ---------------------------------------------------------------------------
# Control flags
# ---------------------------------------------------------------------------


class TestStateTrackerControlFlags:
    def test_run_control_flags_increments_iteration(self):
        st = StateTracker(sid="s", file_store=None, user_id=None)
        st.set_initial_state(
            session_id="s",
            state=None,
            conversation_stats=MagicMock(),
            max_iterations=100,
            max_budget_per_task=None,
        )
        before = st.state.iteration_flag.current_value
        st.run_control_flags()
        assert st.state.iteration_flag.current_value == before + 1

    def test_maybe_increase_limits(self):
        st = StateTracker(sid="s", file_store=None, user_id=None)
        st.set_initial_state(
            session_id="s",
            state=None,
            conversation_stats=MagicMock(),
            max_iterations=100,
            max_budget_per_task=None,
        )
        # increase_limit only bumps when headless_mode=False AND _hit_limit=True
        st.state.iteration_flag._hit_limit = True
        old_max = st.state.iteration_flag.max_value
        st.maybe_increase_control_flags_limits(headless_mode=False)
        assert st.state.iteration_flag.max_value > old_max


# ---------------------------------------------------------------------------
# validate history range
# ---------------------------------------------------------------------------


class TestValidateHistoryRange:
    def test_valid_range(self):
        st = StateTracker(sid="s", file_store=None, user_id=None)
        st.set_initial_state(
            session_id="s",
            state=None,
            conversation_stats=MagicMock(),
            max_iterations=100,
            max_budget_per_task=None,
        )
        assert st._validate_history_range(0, 10) is True

    def test_invalid_range(self):
        st = StateTracker(sid="s", file_store=None, user_id=None)
        st.set_initial_state(
            session_id="s",
            state=None,
            conversation_stats=MagicMock(),
            max_iterations=100,
            max_budget_per_task=None,
        )
        assert st._validate_history_range(20, 5) is False
        assert st.state.history == []
