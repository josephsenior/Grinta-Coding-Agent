"""Tests for backend.storage.data_models.conversation_metadata — ConversationMetadata dataclass."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.core.provider_types import ProviderType
from backend.storage.data_models.conversation_metadata import (
    ConversationMetadata,
    ConversationTrigger,
)


# ── ConversationTrigger enum ─────────────────────────────────────────


class TestConversationTrigger:
    def test_values(self):
        expected = {"gui", "suggested_task", "playbook_management", "external_api", "remote_api_key", "unknown"}
        actual = {t.value for t in ConversationTrigger}
        assert actual == expected

    def test_member_count(self):
        assert len(ConversationTrigger) == 6


# ── ConversationMetadata defaults ────────────────────────────────────


class TestConversationMetadataDefaults:
    def test_required_fields(self):
        md = ConversationMetadata(
            conversation_id="c1",
            title="Test",
            selected_repository=None,
        )
        assert md.conversation_id == "c1"
        assert md.title == "Test"
        assert md.selected_repository is None

    def test_default_optionals(self):
        md = ConversationMetadata(
            conversation_id="c1",
            title="Test",
            selected_repository=None,
        )
        assert md.user_id is None
        assert md.selected_branch is None
        assert md.vcs_provider is None
        assert md.trigger is None
        assert md.pr_number == []
        assert md.llm_model is None
        assert md.accumulated_cost == 0.0
        assert md.prompt_tokens == 0
        assert md.completion_tokens == 0
        assert md.total_tokens == 0

    def test_created_at_auto(self):
        before = datetime.now(UTC)
        md = ConversationMetadata(
            conversation_id="c1",
            title="Test",
            selected_repository=None,
        )
        after = datetime.now(UTC)
        assert before <= md.created_at <= after


# ── ConversationMetadata __post_init__ ───────────────────────────────


class TestConversationMetadataPostInit:
    def test_name_defaults_to_title(self):
        md = ConversationMetadata(
            conversation_id="c1",
            title="My Title",
            selected_repository=None,
        )
        assert md.name == "My Title"

    def test_name_custom(self):
        md = ConversationMetadata(
            conversation_id="c1",
            title="My Title",
            selected_repository=None,
            name="Custom Name",
        )
        assert md.name == "Custom Name"

    def test_last_updated_at_defaults_to_created(self):
        md = ConversationMetadata(
            conversation_id="c1",
            title="Test",
            selected_repository=None,
        )
        assert md.last_updated_at == md.created_at

    def test_last_updated_at_custom(self):
        custom_time = datetime(2024, 1, 1, tzinfo=UTC)
        md = ConversationMetadata(
            conversation_id="c1",
            title="Test",
            selected_repository=None,
            last_updated_at=custom_time,
        )
        assert md.last_updated_at == custom_time


# ── ConversationMetadata full ────────────────────────────────────────


class TestConversationMetadataFull:
    def test_all_fields(self):
        now = datetime.now(UTC)
        md = ConversationMetadata(
            conversation_id="c1",
            title="Full Test",
            selected_repository="org/repo",
            user_id="user1",
            selected_branch="main",
            vcs_provider=ProviderType.ENTERPRISE_SSO,
            last_updated_at=now,
            trigger=ConversationTrigger.GUI,
            pr_number=[10, 20],
            created_at=now,
            llm_model="gpt-4",
            accumulated_cost=1.5,
            prompt_tokens=100,
            completion_tokens=200,
            total_tokens=300,
            name="Custom",
        )
        assert md.selected_repository == "org/repo"
        assert md.user_id == "user1"
        assert md.vcs_provider == ProviderType.ENTERPRISE_SSO
        assert md.trigger == ConversationTrigger.GUI
        assert md.pr_number == [10, 20]
        assert md.accumulated_cost == 1.5
        assert md.total_tokens == 300
