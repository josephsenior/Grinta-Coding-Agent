"""Tests for backend.ledger.compaction — event compaction utilities."""

from typing import Any, cast
from unittest.mock import MagicMock

from backend.ledger.compaction import (
    EventCompactor,
    _edit_path,
    _is_file_edit,
    _is_null,
    _is_state_change,
    _type_name,
)


class TestTypeName:
    """Tests for _type_name function."""

    def test_regular_class(self):
        """Test type name extraction."""
        event = MagicMock(spec=[])
        event.__class__.__name__ = 'FileEditAction'
        assert _type_name(event) == 'FileEditAction'

    def test_builtin_type(self):
        """Test with builtin type."""
        assert _type_name(cast(Any, [])) == 'list'
        assert _type_name(cast(Any, {})) == 'dict'


class TestIsNull:
    """Tests for _is_null function."""

    def test_null_action(self):
        """Test NullAction is identified as null."""
        event = MagicMock()
        event.__class__.__name__ = 'NullAction'
        assert _is_null(event) is True

    def test_null_observation(self):
        """Test NullObservation is identified as null."""
        event = MagicMock()
        event.__class__.__name__ = 'NullObservation'
        assert _is_null(event) is True

    def test_non_null(self):
        """Test non-null events."""
        event = MagicMock()
        event.__class__.__name__ = 'FileEditAction'
        assert _is_null(event) is False


class TestIsStateChange:
    """Tests for _is_state_change function."""

    def test_change_agent_state_action(self):
        """Test ChangeAgentStateAction is identified."""
        event = MagicMock()
        event.__class__.__name__ = 'ChangeAgentStateAction'
        assert _is_state_change(event) is True

    def test_agent_state_changed_observation(self):
        """Test AgentStateChangedObservation is identified."""
        event = MagicMock()
        event.__class__.__name__ = 'AgentStateChangedObservation'
        assert _is_state_change(event) is True

    def test_non_state_change(self):
        """Test non-state-change events."""
        event = MagicMock()
        event.__class__.__name__ = 'FileEditAction'
        assert _is_state_change(event) is False


class TestIsFileEdit:
    """Tests for _is_file_edit function."""

    def test_file_edit_action(self):
        """Test FileEditAction is identified."""
        event = MagicMock()
        event.__class__.__name__ = 'FileEditAction'
        assert _is_file_edit(event) is True

    def test_non_file_edit(self):
        """Test non-file-edit events."""
        event = MagicMock()
        event.__class__.__name__ = 'CmdRunAction'
        assert _is_file_edit(event) is False


class TestEditPath:
    """Tests for _edit_path function."""

    def test_event_with_path(self):
        """Test extracting path attribute."""
        event = MagicMock()
        event.path = 'test.py'
        assert _edit_path(event) == 'test.py'

    def test_event_without_path(self):
        """Test event without path attribute."""
        event = MagicMock(spec=[])
        result = _edit_path(event)
        assert result is None


class TestEventCompactorInit:
    """Tests for EventCompactor initialization."""

    def test_default_initialization(self):
        """Test default parameters."""
        compactor = EventCompactor()
        assert compactor.drop_nulls is True
        assert compactor.fold_state_changes is True
        assert compactor.fold_file_edits is True

    def test_custom_initialization(self):
        """Test custom parameters."""
        compactor = EventCompactor(
            drop_nulls=False,
            fold_state_changes=False,
            fold_file_edits=False,
        )
        assert compactor.drop_nulls is False
        assert compactor.fold_state_changes is False
        assert compactor.fold_file_edits is False


class TestEventCompactorCompact:
    """Tests for EventCompactor.compact method."""

    def test_empty_events(self):
        """Test compacting empty list."""
        compactor = EventCompactor()
        result = compactor.compact([])
        assert result == []

    def test_no_compaction_needed(self):
        """Test events that don't need compaction."""
        event1 = MagicMock()
        event1.__class__.__name__ = 'CmdRunAction'
        event2 = MagicMock()
        event2.__class__.__name__ = 'CmdOutputObservation'

        compactor = EventCompactor()
        result = compactor.compact([event1, event2])
        assert len(result) == 2

    def test_original_not_mutated(self):
        """Test original list is not modified."""
        event = MagicMock()
        event.__class__.__name__ = 'NullAction'
        events: list[Any] = [event]

        compactor = EventCompactor()
        compactor.compact(events)

        # Original should still have the event
        assert len(events) == 1


class TestDropNulls:
    """Tests for EventCompactor._drop_nulls method."""

    def test_removes_null_actions(self):
        """Test null actions are removed."""
        null_event = MagicMock()
        null_event.__class__.__name__ = 'NullAction'
        regular_event = MagicMock()
        regular_event.__class__.__name__ = 'CmdRunAction'

        compactor = EventCompactor()
        result = compactor._drop_nulls([null_event, regular_event])

        assert len(result) == 1
        assert result[0] is regular_event

    def test_removes_null_observations(self):
        """Test null observations are removed."""
        null_event = MagicMock()
        null_event.__class__.__name__ = 'NullObservation'
        regular_event = MagicMock()
        regular_event.__class__.__name__ = 'CmdOutputObservation'

        compactor = EventCompactor()
        result = compactor._drop_nulls([null_event, regular_event])

        assert len(result) == 1
        assert result[0] is regular_event

    def test_all_null(self):
        """Test removing all null events."""
        null1 = MagicMock()
        null1.__class__.__name__ = 'NullAction'
        null2 = MagicMock()
        null2.__class__.__name__ = 'NullObservation'

        compactor = EventCompactor()
        result = compactor._drop_nulls([null1, null2])

        assert result == []


class TestFoldStateChanges:
    """Tests for EventCompactor._fold_state_changes method."""

    def test_single_state_change(self):
        """Test single state change is kept."""
        state_event = MagicMock()
        state_event.__class__.__name__ = 'ChangeAgentStateAction'

        compactor = EventCompactor()
        result = compactor._fold_state_changes([state_event])

        assert len(result) == 1
        assert result[0] is state_event

    def test_consecutive_state_changes_keeps_last_two(self):
        """Test consecutive state changes keep last pair."""
        state1 = MagicMock()
        state1.__class__.__name__ = 'ChangeAgentStateAction'
        state2 = MagicMock()
        state2.__class__.__name__ = 'AgentStateChangedObservation'
        state3 = MagicMock()
        state3.__class__.__name__ = 'ChangeAgentStateAction'
        state4 = MagicMock()
        state4.__class__.__name__ = 'AgentStateChangedObservation'

        compactor = EventCompactor()
        result = compactor._fold_state_changes([state1, state2, state3, state4])

        # Should keep last 2
        assert len(result) == 2
        assert result[0] is state3
        assert result[1] is state4

    def test_mixed_events(self):
        """Test non-state-change events are preserved."""
        state1 = MagicMock()
        state1.__class__.__name__ = 'ChangeAgentStateAction'
        regular = MagicMock()
        regular.__class__.__name__ = 'CmdRunAction'
        state2 = MagicMock()
        state2.__class__.__name__ = 'ChangeAgentStateAction'

        compactor = EventCompactor()
        result = compactor._fold_state_changes([state1, regular, state2])

        assert len(result) == 3


class TestFoldFileEdits:
    """Tests for EventCompactor._fold_file_edits method."""

    def test_single_file_edit(self):
        """Test single file edit is kept."""
        edit = MagicMock()
        edit.__class__.__name__ = 'FileEditAction'
        edit.path = 'test.py'

        compactor = EventCompactor()
        result = compactor._fold_file_edits([edit])

        assert len(result) == 1
        assert result[0] is edit

    def test_consecutive_edits_same_file(self):
        """Test consecutive edits to same file keep only last."""
        edit1 = MagicMock()
        edit1.__class__.__name__ = 'FileEditAction'
        edit1.path = 'test.py'
        edit2 = MagicMock()
        edit2.__class__.__name__ = 'FileEditAction'
        edit2.path = 'test.py'
        edit3 = MagicMock()
        edit3.__class__.__name__ = 'FileEditAction'
        edit3.path = 'test.py'

        compactor = EventCompactor()
        result = compactor._fold_file_edits([edit1, edit2, edit3])

        # Should keep only last edit
        assert len(result) == 1
        assert result[0] is edit3

    def test_edits_different_files(self):
        """Test edits to different files are kept."""
        edit1 = MagicMock()
        edit1.__class__.__name__ = 'FileEditAction'
        edit1.path = 'test1.py'
        edit2 = MagicMock()
        edit2.__class__.__name__ = 'FileEditAction'
        edit2.path = 'test2.py'

        compactor = EventCompactor()
        result = compactor._fold_file_edits([edit1, edit2])

        assert len(result) == 2

    def test_non_edit_breaks_run(self):
        """Test non-edit event breaks the folding run."""
        edit1 = MagicMock()
        edit1.__class__.__name__ = 'FileEditAction'
        edit1.path = 'test.py'
        regular = MagicMock()
        regular.__class__.__name__ = 'CmdRunAction'
        edit2 = MagicMock()
        edit2.__class__.__name__ = 'FileEditAction'
        edit2.path = 'test.py'

        compactor = EventCompactor()
        result = compactor._fold_file_edits([edit1, regular, edit2])

        # Both edits should be kept (different runs)
        assert len(result) == 3


class TestEventCompactorIntegration:
    """Integration tests for EventCompactor."""

    def test_all_compaction_rules(self):
        """Test all compaction rules together."""
        null = MagicMock()
        null.__class__.__name__ = 'NullAction'
        edit1 = MagicMock()
        edit1.__class__.__name__ = 'FileEditAction'
        edit1.path = 'test.py'
        edit2 = MagicMock()
        edit2.__class__.__name__ = 'FileEditAction'
        edit2.path = 'test.py'
        state = MagicMock()
        state.__class__.__name__ = 'ChangeAgentStateAction'

        compactor = EventCompactor()
        result = compactor.compact([null, edit1, edit2, state])

        # null removed, edit2 kept (last of same file), state kept
        assert len(result) == 2

    def test_disabled_compaction(self):
        """Test with all compaction disabled."""
        null = MagicMock()
        null.__class__.__name__ = 'NullAction'
        edit = MagicMock()
        edit.__class__.__name__ = 'FileEditAction'

        compactor = EventCompactor(
            drop_nulls=False,
            fold_state_changes=False,
            fold_file_edits=False,
        )
        result = compactor.compact([null, edit])

        # All events kept
        assert len(result) == 2
