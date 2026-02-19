"""Tests for backend.storage.locations — Conversation storage path helpers (batch 7)."""

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


class TestConversationDirPaths:
    def test_no_user_id(self):
        assert get_conversation_dir("s1") == f"{CONVERSATION_BASE_DIR}/s1/"

    def test_with_user_id(self):
        assert get_conversation_dir("s1", "u1") == "users/u1/conversations/s1/"


class TestConversationEventsPaths:
    def test_events_dir_no_user(self):
        assert (
            get_conversation_events_dir("s1") == f"{CONVERSATION_BASE_DIR}/s1/events/"
        )

    def test_events_dir_with_user(self):
        assert (
            get_conversation_events_dir("s1", "u1")
            == "users/u1/conversations/s1/events/"
        )

    def test_event_filename_no_user(self):
        assert (
            get_conversation_event_filename("s1", 42)
            == f"{CONVERSATION_BASE_DIR}/s1/events/42.json"
        )

    def test_event_filename_with_user(self):
        assert (
            get_conversation_event_filename("s1", 7, "u1")
            == "users/u1/conversations/s1/events/7.json"
        )


class TestConversationFilePaths:
    def test_metadata_no_user(self):
        result = get_conversation_metadata_filename("s1")
        assert result.endswith("metadata.json")

    def test_metadata_with_user(self):
        result = get_conversation_metadata_filename("s1", "u1")
        assert "users/u1" in result and result.endswith("metadata.json")

    def test_init_data(self):
        assert get_conversation_init_data_filename("s1").endswith("init.json")

    def test_agent_state(self):
        assert get_conversation_agent_state_filename("s1").endswith("agent_state.pkl")

    def test_llm_registry(self):
        assert get_conversation_llm_registry_filename("s1").endswith(
            "llm_registry.json"
        )

    def test_stats(self):
        assert get_conversation_stats_filename("s1").endswith("conversation_stats.pkl")

    def test_checkpoints_dir(self):
        assert get_conversation_checkpoints_dir("s1").endswith("checkpoints/")

    def test_checkpoints_dir_with_user(self):
        result = get_conversation_checkpoints_dir("s1", "u1")
        assert "users/u1" in result and result.endswith("checkpoints/")
