"""Tests for backend.storage.locations — conversation path helpers."""

import pytest

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


class TestGetConversationDir:
    def test_without_user_id(self):
        result = get_conversation_dir("sess123")
        assert "sess123" in result
        assert result.endswith("/")

    def test_with_user_id(self):
        result = get_conversation_dir("sess123", user_id="user456")
        assert "users/user456" in result
        assert "conversations/sess123" in result
        assert result.endswith("/")


class TestGetConversationEventsDir:
    def test_without_user(self):
        result = get_conversation_events_dir("s1")
        assert result.endswith("events/")
        assert "s1" in result

    def test_with_user(self):
        result = get_conversation_events_dir("s1", user_id="u1")
        assert result.endswith("events/")
        assert "u1" in result


class TestGetConversationEventFilename:
    def test_event_json(self):
        result = get_conversation_event_filename("s1", 42)
        assert result.endswith("42.json")

    def test_event_with_user(self):
        result = get_conversation_event_filename("s1", 0, user_id="u1")
        assert result.endswith("0.json")
        assert "u1" in result


class TestGetConversationMetadataFilename:
    def test_metadata(self):
        result = get_conversation_metadata_filename("s1")
        assert result.endswith("metadata.json")

    def test_metadata_with_user(self):
        result = get_conversation_metadata_filename("s1", "u1")
        assert result.endswith("metadata.json")
        assert "u1" in result


class TestGetConversationInitDataFilename:
    def test_init(self):
        result = get_conversation_init_data_filename("s1")
        assert result.endswith("init.json")


class TestGetConversationAgentStateFilename:
    def test_agent_state(self):
        result = get_conversation_agent_state_filename("s1")
        assert result.endswith("agent_state.pkl")


class TestGetConversationLLMRegistryFilename:
    def test_llm_registry(self):
        result = get_conversation_llm_registry_filename("s1")
        assert result.endswith("llm_registry.json")


class TestGetConversationStatsFilename:
    def test_stats(self):
        result = get_conversation_stats_filename("s1")
        assert result.endswith("conversation_stats.pkl")


class TestGetConversationCheckpointsDir:
    def test_checkpoints(self):
        result = get_conversation_checkpoints_dir("s1")
        assert result.endswith("checkpoints/")

    def test_checkpoints_with_user(self):
        result = get_conversation_checkpoints_dir("s1", "u1")
        assert result.endswith("checkpoints/")
        assert "u1" in result


class TestPathConsistency:
    """Verify helper paths nest correctly under conversation_dir."""

    def test_events_under_conversation(self):
        conv_dir = get_conversation_dir("s1")
        events_dir = get_conversation_events_dir("s1")
        assert events_dir.startswith(conv_dir)

    def test_metadata_under_conversation(self):
        conv_dir = get_conversation_dir("s1")
        meta = get_conversation_metadata_filename("s1")
        assert meta.startswith(conv_dir)

    def test_event_file_under_events(self):
        events_dir = get_conversation_events_dir("s1")
        event_file = get_conversation_event_filename("s1", 10)
        assert event_file.startswith(events_dir)
