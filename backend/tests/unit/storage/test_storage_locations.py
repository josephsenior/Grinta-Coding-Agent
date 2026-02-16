"""Unit tests for backend.storage.locations — path-building helpers."""

from __future__ import annotations


from backend.core.constants import CONVERSATION_BASE_DIR
from backend.storage.locations import (
    get_conversation_agent_state_filename,
    get_conversation_checkpoints_dir,
    get_conversation_dir,
    get_conversation_event_filename,
    get_conversation_events_dir,
    get_conversation_init_data_filename,
    get_conversation_llm_registry_filename,
    get_conversation_metadata_filename,
    get_conversation_stats_filename,
)


# ---------------------------------------------------------------------------
# get_conversation_dir
# ---------------------------------------------------------------------------


class TestGetConversationDir:
    def test_without_user(self):
        assert get_conversation_dir("s1") == f"{CONVERSATION_BASE_DIR}/s1/"

    def test_with_user(self):
        assert get_conversation_dir("s1", "u1") == "users/u1/conversations/s1/"


# ---------------------------------------------------------------------------
# get_conversation_events_dir
# ---------------------------------------------------------------------------


class TestGetConversationEventsDir:
    def test_without_user(self):
        result = get_conversation_events_dir("s1")
        assert result.endswith("/events/")
        assert "s1" in result

    def test_with_user(self):
        result = get_conversation_events_dir("s1", "u1")
        assert "u1" in result
        assert result.endswith("/events/")


# ---------------------------------------------------------------------------
# get_conversation_event_filename
# ---------------------------------------------------------------------------


class TestGetEventFilename:
    def test_format(self):
        result = get_conversation_event_filename("s1", 42)
        assert result.endswith("42.json")
        assert "events/" in result

    def test_with_user(self):
        result = get_conversation_event_filename("s1", 7, "u1")
        assert "u1" in result
        assert result.endswith("7.json")


# ---------------------------------------------------------------------------
# get_conversation_metadata_filename
# ---------------------------------------------------------------------------


class TestMetadata:
    def test_format(self):
        result = get_conversation_metadata_filename("s1")
        assert result.endswith("metadata.json")

    def test_with_user(self):
        result = get_conversation_metadata_filename("s1", "u1")
        assert "u1" in result


# ---------------------------------------------------------------------------
# Other filenames
# ---------------------------------------------------------------------------


class TestOtherFilenames:
    def test_init_data(self):
        result = get_conversation_init_data_filename("s1")
        assert result.endswith("init.json")

    def test_agent_state(self):
        result = get_conversation_agent_state_filename("s1")
        assert result.endswith("agent_state.pkl")

    def test_llm_registry(self):
        result = get_conversation_llm_registry_filename("s1")
        assert result.endswith("llm_registry.json")

    def test_stats(self):
        result = get_conversation_stats_filename("s1")
        assert result.endswith("conversation_stats.pkl")

    def test_checkpoints_dir(self):
        result = get_conversation_checkpoints_dir("s1")
        assert result.endswith("checkpoints/")

    # With user_id variants

    def test_init_data_user(self):
        result = get_conversation_init_data_filename("s1", "u1")
        assert "u1" in result

    def test_agent_state_user(self):
        result = get_conversation_agent_state_filename("s1", "u1")
        assert "u1" in result

    def test_llm_registry_user(self):
        result = get_conversation_llm_registry_filename("s1", "u1")
        assert "u1" in result

    def test_stats_user(self):
        result = get_conversation_stats_filename("s1", "u1")
        assert "u1" in result

    def test_checkpoints_dir_user(self):
        result = get_conversation_checkpoints_dir("s1", "u1")
        assert "u1" in result
