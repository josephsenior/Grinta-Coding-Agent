"""Tests for backend.persistence.data_models.conversation_status — ConversationStatus enum."""

from __future__ import annotations


from backend.persistence.data_models.conversation_status import ConversationStatus


class TestConversationStatusEnum:
    def test_values(self):
        assert ConversationStatus.STARTING.value == "starting"
        assert ConversationStatus.RUNNING.value == "running"
        assert ConversationStatus.STOPPED.value == "stopped"
        assert ConversationStatus.PAUSED.value == "paused"
        assert ConversationStatus.ARCHIVED.value == "archived"
        assert ConversationStatus.UNKNOWN.value == "unknown"

    def test_member_count(self):
        assert len(ConversationStatus) == 6


class TestFromRuntimeStatus:
    def test_none_returns_unknown(self):
        assert (
            ConversationStatus.from_runtime_status(None) is ConversationStatus.UNKNOWN
        )

    def test_empty_returns_unknown(self):
        assert ConversationStatus.from_runtime_status("") is ConversationStatus.UNKNOWN

    # STARTING aliases
    def test_starting(self):
        assert (
            ConversationStatus.from_runtime_status("starting")
            is ConversationStatus.STARTING
        )

    def test_starting_case_insensitive(self):
        assert (
            ConversationStatus.from_runtime_status("STARTING")
            is ConversationStatus.STARTING
        )

    # RUNNING aliases
    def test_running(self):
        assert (
            ConversationStatus.from_runtime_status("running")
            is ConversationStatus.RUNNING
        )

    def test_active(self):
        assert (
            ConversationStatus.from_runtime_status("active")
            is ConversationStatus.RUNNING
        )

    def test_started(self):
        assert (
            ConversationStatus.from_runtime_status("started")
            is ConversationStatus.RUNNING
        )

    # STOPPED aliases
    def test_stopped(self):
        assert (
            ConversationStatus.from_runtime_status("stopped")
            is ConversationStatus.STOPPED
        )

    def test_stopping(self):
        assert (
            ConversationStatus.from_runtime_status("stopping")
            is ConversationStatus.STOPPED
        )

    # PAUSED aliases
    def test_paused(self):
        assert (
            ConversationStatus.from_runtime_status("paused")
            is ConversationStatus.PAUSED
        )

    def test_pause(self):
        assert (
            ConversationStatus.from_runtime_status("pause") is ConversationStatus.PAUSED
        )

    # ARCHIVED aliases
    def test_archived(self):
        assert (
            ConversationStatus.from_runtime_status("archived")
            is ConversationStatus.ARCHIVED
        )

    def test_deleted(self):
        assert (
            ConversationStatus.from_runtime_status("deleted")
            is ConversationStatus.ARCHIVED
        )

    # UNKNOWN fallback
    def test_unknown_string(self):
        assert (
            ConversationStatus.from_runtime_status("foo_bar_baz")
            is ConversationStatus.UNKNOWN
        )

    def test_case_insensitive_active(self):
        assert (
            ConversationStatus.from_runtime_status("Active")
            is ConversationStatus.RUNNING
        )

    def test_case_insensitive_pause(self):
        assert (
            ConversationStatus.from_runtime_status("PAUSE") is ConversationStatus.PAUSED
        )
