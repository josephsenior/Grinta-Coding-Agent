"""Unit tests for backend.events.compaction — batch event compaction."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.events.compaction import EventCompactor


# ---------------------------------------------------------------------------
# Helpers — lightweight event stubs
# ---------------------------------------------------------------------------


def _ev(name: str, **attrs) -> MagicMock:
    """Create a mock event whose type().__name__ returns *name*."""
    ev = MagicMock()
    ev.__class__ = type(name, (), {})
    type(ev).__name__ = name
    for k, v in attrs.items():
        setattr(ev, k, v)
    return ev


# ---------------------------------------------------------------------------
# Null removal
# ---------------------------------------------------------------------------


class TestDropNulls:
    def test_removes_null_actions(self):
        events = [_ev("NullAction"), _ev("MessageAction"), _ev("NullAction")]
        c = EventCompactor()
        result = c.compact(events)
        assert len(result) == 1
        assert type(result[0]).__name__ == "MessageAction"

    def test_removes_null_observations(self):
        events = [_ev("NullObservation"), _ev("CmdRunAction")]
        result = EventCompactor().compact(events)
        assert len(result) == 1

    def test_all_nulls_returns_empty(self):
        events = [_ev("NullAction"), _ev("NullObservation")]
        result = EventCompactor().compact(events)
        assert result == []

    def test_disabled(self):
        events = [_ev("NullAction"), _ev("MessageAction")]
        result = EventCompactor(drop_nulls=False).compact(events)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# State-change folding
# ---------------------------------------------------------------------------


class TestFoldStateChanges:
    def test_consecutive_collapsed(self):
        events = [
            _ev("ChangeAgentStateAction"),
            _ev("AgentStateChangedObservation"),
            _ev("ChangeAgentStateAction"),
            _ev("AgentStateChangedObservation"),
        ]
        result = EventCompactor(drop_nulls=False).compact(events)
        # Should keep only last pair
        assert len(result) == 2

    def test_single_pair_kept(self):
        events = [
            _ev("ChangeAgentStateAction"),
            _ev("AgentStateChangedObservation"),
        ]
        result = EventCompactor(drop_nulls=False).compact(events)
        assert len(result) == 2

    def test_non_consecutive_not_folded(self):
        events = [
            _ev("ChangeAgentStateAction"),
            _ev("AgentStateChangedObservation"),
            _ev("MessageAction"),
            _ev("ChangeAgentStateAction"),
            _ev("AgentStateChangedObservation"),
        ]
        result = EventCompactor(drop_nulls=False).compact(events)
        # Both pairs kept because they're separated by MessageAction
        assert len(result) == 5

    def test_single_state_event_kept(self):
        events = [_ev("ChangeAgentStateAction")]
        result = EventCompactor(drop_nulls=False).compact(events)
        assert len(result) == 1

    def test_disabled(self):
        events = [
            _ev("ChangeAgentStateAction"),
            _ev("AgentStateChangedObservation"),
            _ev("ChangeAgentStateAction"),
            _ev("AgentStateChangedObservation"),
        ]
        result = EventCompactor(drop_nulls=False, fold_state_changes=False).compact(events)
        assert len(result) == 4

    def test_three_consecutive_pairs(self):
        events = [
            _ev("ChangeAgentStateAction"),
            _ev("AgentStateChangedObservation"),
            _ev("ChangeAgentStateAction"),
            _ev("AgentStateChangedObservation"),
            _ev("ChangeAgentStateAction"),
            _ev("AgentStateChangedObservation"),
        ]
        result = EventCompactor(drop_nulls=False).compact(events)
        assert len(result) == 2  # last pair


# ---------------------------------------------------------------------------
# File-edit folding
# ---------------------------------------------------------------------------


class TestFoldFileEdits:
    def test_same_path_collapsed(self):
        events = [
            _ev("FileEditAction", path="a.py"),
            _ev("FileEditAction", path="a.py"),
            _ev("FileEditAction", path="a.py"),
        ]
        result = EventCompactor(drop_nulls=False, fold_state_changes=False).compact(events)
        assert len(result) == 1
        assert result[0] is events[2]  # last edit

    def test_different_paths_kept(self):
        events = [
            _ev("FileEditAction", path="a.py"),
            _ev("FileEditAction", path="b.py"),
        ]
        result = EventCompactor(drop_nulls=False, fold_state_changes=False).compact(events)
        assert len(result) == 2

    def test_interrupted_run_both_kept(self):
        events = [
            _ev("FileEditAction", path="a.py"),
            _ev("CmdRunAction"),
            _ev("FileEditAction", path="a.py"),
        ]
        result = EventCompactor(drop_nulls=False, fold_state_changes=False).compact(events)
        assert len(result) == 3

    def test_disabled(self):
        events = [
            _ev("FileEditAction", path="a.py"),
            _ev("FileEditAction", path="a.py"),
        ]
        result = EventCompactor(drop_nulls=False, fold_state_changes=False, fold_file_edits=False).compact(events)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Combined rules
# ---------------------------------------------------------------------------


class TestCombinedRules:
    def test_all_rules_apply(self):
        events = [
            _ev("NullAction"),
            _ev("NullObservation"),
            _ev("ChangeAgentStateAction"),
            _ev("AgentStateChangedObservation"),
            _ev("ChangeAgentStateAction"),
            _ev("AgentStateChangedObservation"),
            _ev("FileEditAction", path="x.py"),
            _ev("FileEditAction", path="x.py"),
            _ev("MessageAction"),
        ]
        result = EventCompactor().compact(events)
        # nulls removed (2), state changes folded to 2, edits folded to 1, message kept
        assert len(result) == 4

    def test_empty_list(self):
        assert EventCompactor().compact([]) == []

    def test_no_compaction_needed(self):
        events = [_ev("MessageAction"), _ev("CmdRunAction")]
        result = EventCompactor().compact(events)
        assert len(result) == 2

    def test_original_list_not_mutated(self):
        events = [_ev("NullAction"), _ev("MessageAction")]
        original_len = len(events)
        EventCompactor().compact(events)
        assert len(events) == original_len
