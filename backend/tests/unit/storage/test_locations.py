"""Tests for backend.storage.locations — conversation path helpers."""

from backend.storage.locations import (
    get_conversation_dir,
    get_conversation_events_dir,
    get_conversation_event_filename,
    get_conversation_metadata_filename,
    get_conversation_init_data_filename,
    get_conversation_agent_state_filename,
    get_conversation_llm_registry_filename,
    get_conversation_stats_filename,
    get_conversation_checkpoints_dir,
)


class TestGetConversationDir:
    """Tests for get_conversation_dir function."""

    def test_without_user_id(self):
        """Test conversation dir without user_id."""
        result = get_conversation_dir("session123")
        assert result == "sessions/session123/"

    def test_with_user_id(self):
        """Test conversation dir with user_id."""
        result = get_conversation_dir("session123", user_id="user456")
        assert result == "users/user456/conversations/session123/"

    def test_different_session_ids(self):
        """Test different session IDs produce different paths."""
        result1 = get_conversation_dir("session1")
        result2 = get_conversation_dir("session2")
        assert result1 != result2
        assert "session1" in result1
        assert "session2" in result2

    def test_ends_with_slash(self):
        """Test result ends with slash."""
        result = get_conversation_dir("test")
        assert result.endswith("/")


class TestGetConversationEventsDir:
    """Tests for get_conversation_events_dir function."""

    def test_without_user_id(self):
        """Test events dir without user_id."""
        result = get_conversation_events_dir("session123")
        assert result == "sessions/session123/events/"

    def test_with_user_id(self):
        """Test events dir with user_id."""
        result = get_conversation_events_dir("session123", user_id="user456")
        assert result == "users/user456/conversations/session123/events/"

    def test_ends_with_events_slash(self):
        """Test result ends with events/."""
        result = get_conversation_events_dir("test")
        assert result.endswith("events/")


class TestGetConversationEventFilename:
    """Tests for get_conversation_event_filename function."""

    def test_without_user_id(self):
        """Test event filename without user_id."""
        result = get_conversation_event_filename("session123", id=5)
        assert result == "sessions/session123/events/5.json"

    def test_with_user_id(self):
        """Test event filename with user_id."""
        result = get_conversation_event_filename("session123", id=10, user_id="user456")
        assert result == "users/user456/conversations/session123/events/10.json"

    def test_different_event_ids(self):
        """Test different event IDs."""
        result1 = get_conversation_event_filename("session", id=1)
        result2 = get_conversation_event_filename("session", id=2)
        assert "1.json" in result1
        assert "2.json" in result2

    def test_zero_event_id(self):
        """Test event ID of zero."""
        result = get_conversation_event_filename("session", id=0)
        assert result.endswith("0.json")


class TestGetConversationMetadataFilename:
    """Tests for get_conversation_metadata_filename function."""

    def test_without_user_id(self):
        """Test metadata filename without user_id."""
        result = get_conversation_metadata_filename("session123")
        assert result == "sessions/session123/metadata.json"

    def test_with_user_id(self):
        """Test metadata filename with user_id."""
        result = get_conversation_metadata_filename("session123", user_id="user456")
        assert result == "users/user456/conversations/session123/metadata.json"

    def test_ends_with_metadata_json(self):
        """Test result ends with metadata.json."""
        result = get_conversation_metadata_filename("test")
        assert result.endswith("metadata.json")


class TestGetConversationInitDataFilename:
    """Tests for get_conversation_init_data_filename function."""

    def test_without_user_id(self):
        """Test init data filename without user_id."""
        result = get_conversation_init_data_filename("session123")
        assert result == "sessions/session123/init.json"

    def test_with_user_id(self):
        """Test init data filename with user_id."""
        result = get_conversation_init_data_filename("session123", user_id="user456")
        assert result == "users/user456/conversations/session123/init.json"

    def test_ends_with_init_json(self):
        """Test result ends with init.json."""
        result = get_conversation_init_data_filename("test")
        assert result.endswith("init.json")


class TestGetConversationAgentStateFilename:
    """Tests for get_conversation_agent_state_filename function."""

    def test_without_user_id(self):
        """Test agent state filename without user_id."""
        result = get_conversation_agent_state_filename("session123")
        assert result == "sessions/session123/agent_state.pkl"

    def test_with_user_id(self):
        """Test agent state filename with user_id."""
        result = get_conversation_agent_state_filename("session123", user_id="user456")
        assert result == "users/user456/conversations/session123/agent_state.pkl"

    def test_ends_with_pkl(self):
        """Test result ends with .pkl."""
        result = get_conversation_agent_state_filename("test")
        assert result.endswith("agent_state.pkl")


class TestGetConversationLlmRegistryFilename:
    """Tests for get_conversation_llm_registry_filename function."""

    def test_without_user_id(self):
        """Test LLM registry filename without user_id."""
        result = get_conversation_llm_registry_filename("session123")
        assert result == "sessions/session123/llm_registry.json"

    def test_with_user_id(self):
        """Test LLM registry filename with user_id."""
        result = get_conversation_llm_registry_filename("session123", user_id="user456")
        assert result == "users/user456/conversations/session123/llm_registry.json"

    def test_ends_with_llm_registry_json(self):
        """Test result ends with llm_registry.json."""
        result = get_conversation_llm_registry_filename("test")
        assert result.endswith("llm_registry.json")


class TestGetConversationStatsFilename:
    """Tests for get_conversation_stats_filename function."""

    def test_without_user_id(self):
        """Test stats filename without user_id."""
        result = get_conversation_stats_filename("session123")
        assert result == "sessions/session123/conversation_stats.pkl"

    def test_with_user_id(self):
        """Test stats filename with user_id."""
        result = get_conversation_stats_filename("session123", user_id="user456")
        assert result == "users/user456/conversations/session123/conversation_stats.pkl"

    def test_ends_with_pkl(self):
        """Test result ends with .pkl."""
        result = get_conversation_stats_filename("test")
        assert result.endswith("conversation_stats.pkl")


class TestGetConversationCheckpointsDir:
    """Tests for get_conversation_checkpoints_dir function."""

    def test_without_user_id(self):
        """Test checkpoints dir without user_id."""
        result = get_conversation_checkpoints_dir("session123")
        assert result == "sessions/session123/checkpoints/"

    def test_with_user_id(self):
        """Test checkpoints dir with user_id."""
        result = get_conversation_checkpoints_dir("session123", user_id="user456")
        assert result == "users/user456/conversations/session123/checkpoints/"

    def test_ends_with_checkpoints_slash(self):
        """Test result ends with checkpoints/."""
        result = get_conversation_checkpoints_dir("test")
        assert result.endswith("checkpoints/")


class TestPathConsistency:
    """Tests for consistency across path functions."""

    def test_all_paths_use_same_base(self):
        """Test all path functions use same conversation_dir base."""
        sid = "test_session"
        user_id = "test_user"

        conv_dir = get_conversation_dir(sid, user_id)
        events_dir = get_conversation_events_dir(sid, user_id)
        metadata = get_conversation_metadata_filename(sid, user_id)
        init_data = get_conversation_init_data_filename(sid, user_id)
        agent_state = get_conversation_agent_state_filename(sid, user_id)

        # All should start with the same conversation dir
        assert events_dir.startswith(conv_dir)
        assert metadata.startswith(conv_dir)
        assert init_data.startswith(conv_dir)
        assert agent_state.startswith(conv_dir)

    def test_user_paths_vs_global_paths(self):
        """Test user-specific paths differ from global paths."""
        sid = "session"

        global_dir = get_conversation_dir(sid)
        user_dir = get_conversation_dir(sid, user_id="user123")

        assert global_dir != user_dir
        assert "users/" in user_dir
        assert "users/" not in global_dir

    def test_event_filename_in_events_dir(self):
        """Test event filename is within events directory."""
        sid = "session"
        events_dir = get_conversation_events_dir(sid)
        event_file = get_conversation_event_filename(sid, id=1)

        assert event_file.startswith(events_dir)
