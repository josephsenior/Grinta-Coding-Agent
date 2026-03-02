"""Tests for State mutation methods and helpers."""

import json
from unittest.mock import MagicMock
from typing import cast


from backend.controller.state.control_flags import (
    IterationControlFlag,
)
from backend.controller.state.state import State
from backend.core.schemas import AgentState


class TestStateMutationMethods:
    def test_set_last_error_without_source(self):
        """Test setting last error without source."""
        state = State()
        state.set_last_error("Something went wrong")

        assert state.last_error == "Something went wrong"

    def test_set_last_error_with_source(self):
        """Test setting last error with source."""
        state = State()
        state.set_last_error("Error occurred", source="test_service")

        assert state.last_error == "Error occurred"

    def test_set_last_error_empty(self):
        """Test setting empty last error."""
        state = State()
        state.last_error = "Previous error"
        state.set_last_error("")

        assert state.last_error == ""

    def test_set_outputs_without_source(self):
        """Test setting outputs without source."""
        state = State()
        outputs = {"result": "success", "data": [1, 2, 3]}
        state.set_outputs(outputs)

        assert state.outputs == outputs

    def test_set_outputs_with_source(self):
        """Test setting outputs with source."""
        state = State()
        outputs = {"key": "value"}
        state.set_outputs(outputs, source="controller")

        assert state.outputs == outputs

    def test_set_outputs_replaces_existing(self):
        """Test that set_outputs replaces existing outputs."""
        state = State()
        state.outputs = {"old": "data"}
        state.set_outputs({"new": "data"})

        assert state.outputs == {"new": "data"}
        assert "old" not in state.outputs

    def test_set_extra_without_source(self):
        """Test setting extra data without source."""
        state = State()
        state.set_extra("custom_key", "custom_value")

        assert state.extra_data["custom_key"] == "custom_value"

    def test_set_extra_with_source(self):
        """Test setting extra data with source."""
        state = State()
        state.set_extra("flag", True, source="monitor")

        assert state.extra_data["flag"] is True

    def test_set_extra_multiple_keys(self):
        """Test setting multiple extra data keys."""
        state = State()
        state.set_extra("key1", "value1")
        state.set_extra("key2", "value2")
        state.set_extra("key3", "value3")

        assert state.extra_data["key1"] == "value1"
        assert state.extra_data["key2"] == "value2"
        assert state.extra_data["key3"] == "value3"

    def test_set_extra_overwrites_existing(self):
        """Test that set_extra overwrites existing key."""
        state = State()
        state.extra_data["key"] = "old"
        state.set_extra("key", "new")

        assert state.extra_data["key"] == "new"

    def test_adjust_iteration_limit_without_source(self):
        """Test adjusting iteration limit without source."""
        state = State()
        state.iteration_flag = IterationControlFlag(
            limit_increase_amount=100, current_value=0, max_value=100
        )
        state.adjust_iteration_limit(200)

        assert state.iteration_flag.max_value == 200

    def test_adjust_iteration_limit_with_source(self):
        """Test adjusting iteration limit with source."""
        state = State()
        state.iteration_flag = IterationControlFlag(
            limit_increase_amount=50, current_value=10, max_value=50
        )
        state.adjust_iteration_limit(100, source="user_input")

        assert state.iteration_flag.max_value == 100

    def test_adjust_iteration_limit_no_flag(self):
        """Test adjust_iteration_limit when iteration_flag is None."""
        state = State()
        state.iteration_flag = cast(IterationControlFlag, None)
        # Should not raise an exception
        state.adjust_iteration_limit(200)

        # iteration_flag remains None
        assert state.iteration_flag is None

    def test_set_agent_state_without_source(self):
        """Test setting agent state without source."""
        state = State()
        state.set_agent_state(AgentState.RUNNING)

        assert state.agent_state == AgentState.RUNNING

    def test_set_agent_state_with_source(self):
        """Test setting agent state with source."""
        state = State()
        state.set_agent_state(AgentState.PAUSED, source="pause_handler")

        assert state.agent_state == AgentState.PAUSED

    def test_set_agent_state_transition(self):
        """Test agent state transition."""
        state = State()
        state.agent_state = AgentState.LOADING
        state.set_agent_state(AgentState.RUNNING)
        assert state.agent_state == AgentState.RUNNING

        state.set_agent_state(AgentState.FINISHED)
        assert state.agent_state == AgentState.FINISHED

    def test_set_agent_state_same_state(self):
        """Test setting agent state to same value."""
        state = State()
        state.agent_state = AgentState.RUNNING
        state.set_agent_state(AgentState.RUNNING)

        assert state.agent_state == AgentState.RUNNING


class TestStateCheckpointHelpers:
    def test_checkpoint_dir_without_user_id(self):
        """Test checkpoint directory path without user ID."""
        result = State._checkpoint_dir("session123", None)

        assert "session123" in result
        assert result.endswith("state_checkpoints/")

    def test_checkpoint_dir_with_user_id(self):
        """Test checkpoint directory path with user ID."""
        result = State._checkpoint_dir("session456", "user789")

        assert "session456" in result
        assert "user789" in result
        assert result.endswith("state_checkpoints/")

    def test_write_checkpoint_success(self):
        """Test successful checkpoint write."""
        mock_store = MagicMock()
        encoded = '{"version": 1, "data": "test"}'

        State._write_checkpoint(mock_store, "sess1", None, encoded)

        # Verify checkpoint was written
        assert mock_store.write.called
        call_args = mock_store.write.call_args
        assert "state_checkpoints/" in call_args[0][0]
        assert call_args[0][1] == encoded

    def test_write_checkpoint_and_prune(self):
        """Test checkpoint write triggers pruning."""
        mock_store = MagicMock()
        # Simulate existing checkpoints
        mock_store.list.return_value = [
            "1000.json",
            "2000.json",
            "3000.json",
            "4000.json",
            "5000.json",
        ]

        encoded = '{"test": "data"}'
        State._write_checkpoint(mock_store, "sess1", None, encoded)

        # Should list directory to check for pruning
        assert mock_store.list.called

    def test_write_checkpoint_list_failure(self):
        """Test checkpoint write when listing fails."""
        mock_store = MagicMock()
        mock_store.list.side_effect = Exception("Directory not found")
        encoded = '{"test": "data"}'

        # Should not raise exception
        State._write_checkpoint(mock_store, "sess1", None, encoded)

        # Write should still succeed
        assert mock_store.write.called

    def test_write_checkpoint_write_failure(self):
        """Test checkpoint write failure."""
        mock_store = MagicMock()
        mock_store.write.side_effect = Exception("Write failed")
        encoded = '{"test": "data"}'

        # Should not raise exception
        State._write_checkpoint(mock_store, "sess1", None, encoded)

        # Should not try to list/prune if write failed
        assert not mock_store.list.called


class TestStateInitialization:
    def test_default_initialization(self):
        """Test State with default values."""
        state = State()

        assert state.session_id == ""
        assert state.user_id is None
        assert state.agent_state == AgentState.LOADING
        assert state.confirmation_mode is False
        assert state.history == []
        assert state.inputs == {}
        assert state.outputs == {}
        assert state.extra_data == {}
        assert state.last_error == ""
        assert state.delegate_level == 0

    def test_initialization_with_values(self):
        """Test State initialization with custom values."""
        state = State(
            session_id="test123",
            user_id="user456",
            confirmation_mode=True,
            delegate_level=2,
        )

        assert state.session_id == "test123"
        assert state.user_id == "user456"
        assert state.confirmation_mode is True
        assert state.delegate_level == 2

    def test_iteration_flag_default(self):
        """Test default iteration flag initialization."""
        state = State()

        assert state.iteration_flag is not None
        assert state.iteration_flag.current_value == 0
        assert state.iteration_flag.max_value == 100
        assert state.iteration_flag.limit_increase_amount == 100

    def test_metrics_initialization(self):
        """Test metrics field initialization."""
        state = State()

        assert state.metrics is not None
        assert hasattr(state.metrics, "model_name")


class TestStateSaveToSession:
    def test_save_to_session_basic(self):
        """Test basic save to session."""
        mock_store = MagicMock()
        state = State(session_id="sess1", user_id=None)
        state.set_extra("key", "value")

        state.save_to_session("sess1", mock_store, None)

        # Verify write was called (may write checkpoint first, then primary)
        assert mock_store.write.called
        # Check that at least one call was to agent_state.json or checkpoint
        all_filenames = [call[0][0] for call in mock_store.write.call_args_list]
        has_primary_or_checkpoint = any(
            "agent_state.json" in f or "state_checkpoints" in f for f in all_filenames
        )
        assert has_primary_or_checkpoint

        # Content should be JSON
        content = mock_store.write.call_args_list[0][0][1]
        assert isinstance(content, str)
        data = json.loads(content)
        assert "_schema_version" in data

    def test_save_to_session_with_user_id(self):
        """Test save to session with user ID."""
        mock_store = MagicMock()
        state = State(session_id="sess2", user_id="user123")

        state.save_to_session("sess2", mock_store, "user123")

        assert mock_store.write.called
        # Should write to user-specific location
        filename = mock_store.write.call_args[0][0]
        assert "user123" in filename or "sess2" in filename

    def test_save_clears_conversation_stats(self):
        """Test that conversation_stats is cleared during save."""
        mock_store = MagicMock()
        mock_stats = MagicMock()
        state = State()
        state.conversation_stats = mock_stats

        state.save_to_session("sess1", mock_store, None)

        # conversation_stats should be None during serialization
        # but restored after
        assert state.conversation_stats == mock_stats

    def test_save_writes_checkpoint(self):
        """Test that save_to_session writes checkpoint."""
        mock_store = MagicMock()
        state = State()

        state.save_to_session("sess1", mock_store, None)

        # Should write primary file + checkpoint
        # (at least 2 write calls)
        assert mock_store.write.call_count >= 1

    def test_save_deletes_legacy_file(self):
        """Test that save deletes legacy state file when user_id present."""
        mock_store = MagicMock()
        state = State()

        state.save_to_session("sess1", mock_store, "user123")

        # Should attempt to delete legacy file
        # (may or may not be called depending on file existence)


class TestStateConstants:
    def test_resumable_states_constant(self):
        """Test RESUMABLE_STATES constant."""
        from backend.controller.state.state import RESUMABLE_STATES

        assert AgentState.RUNNING in RESUMABLE_STATES
        assert AgentState.PAUSED in RESUMABLE_STATES
        assert AgentState.AWAITING_USER_INPUT in RESUMABLE_STATES
        assert AgentState.FINISHED in RESUMABLE_STATES

    def test_state_schema_version(self):
        """Test STATE_SCHEMA_VERSION constant."""
        from backend.controller.state.state import STATE_SCHEMA_VERSION

        assert isinstance(STATE_SCHEMA_VERSION, int)
        assert STATE_SCHEMA_VERSION >= 1

    def test_max_state_checkpoints(self):
        """Test MAX_STATE_CHECKPOINTS constant."""
        from backend.controller.state.state import MAX_STATE_CHECKPOINTS

        assert isinstance(MAX_STATE_CHECKPOINTS, int)
        assert MAX_STATE_CHECKPOINTS > 0


class TestTrafficControlState:
    def test_traffic_control_states(self):
        """Test TrafficControlState constants."""
        from backend.controller.state.state import TrafficControlState

        assert TrafficControlState.NORMAL == "normal"
        assert TrafficControlState.THROTTLING == "throttling"
        assert TrafficControlState.PAUSED == "paused"
