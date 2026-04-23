"""Tests for backend.persistence.data_models.conversation_metadata — ConversationMetadata dataclass."""

from __future__ import annotations

from datetime import UTC, datetime

from backend.core.provider_types import ProviderType
from backend.persistence.data_models.conversation_metadata import (
    ConversationMetadata,
    ConversationTrigger,
)

# ── ConversationTrigger enum ─────────────────────────────────────────


class TestConversationTrigger:
    def test_values(self):
        expected = {
            'gui',
            'suggested_task',
            'playbook_management',
            'external_api',
            'unknown',
        }
        actual = {t.value for t in ConversationTrigger}
        assert actual == expected

    def test_member_count(self):
        assert len(ConversationTrigger) == 5


# ── ConversationMetadata defaults ────────────────────────────────────


class TestConversationMetadataDefaults:
    def test_required_fields(self):
        md = ConversationMetadata(
            conversation_id='c1',
            title='Test',
            selected_repository=None,
        )
        assert md.conversation_id == 'c1'
        assert md.title == 'Test'
        assert md.selected_repository is None

    def test_default_optionals(self):
        md = ConversationMetadata(
            conversation_id='c1',
            title='Test',
            selected_repository=None,
        )
        assert (
            md.user_id,
            md.selected_branch,
            md.vcs_provider,
            md.trigger,
            md.pr_number,
            md.llm_model,
            md.accumulated_cost,
            md.prompt_tokens,
            md.completion_tokens,
            md.total_tokens,
        ) == (None, None, None, None, [], None, 0.0, 0, 0, 0)

    def test_created_at_auto(self):
        before = datetime.now(UTC)
        md = ConversationMetadata(
            conversation_id='c1',
            title='Test',
            selected_repository=None,
        )
        after = datetime.now(UTC)
        assert before <= md.created_at <= after


# ── ConversationMetadata __post_init__ ───────────────────────────────


class TestConversationMetadataPostInit:
    def test_name_defaults_to_title(self):
        md = ConversationMetadata(
            conversation_id='c1',
            title='My Title',
            selected_repository=None,
        )
        assert md.name == 'My Title'

    def test_name_custom(self):
        md = ConversationMetadata(
            conversation_id='c1',
            title='My Title',
            selected_repository=None,
            name='Custom Name',
        )
        assert md.name == 'Custom Name'

    def test_last_updated_at_defaults_to_created(self):
        md = ConversationMetadata(
            conversation_id='c1',
            title='Test',
            selected_repository=None,
        )
        assert md.last_updated_at == md.created_at

    def test_last_updated_at_custom(self):
        custom_time = datetime(2024, 1, 1, tzinfo=UTC)
        md = ConversationMetadata(
            conversation_id='c1',
            title='Test',
            selected_repository=None,
            last_updated_at=custom_time,
        )
        assert md.last_updated_at == custom_time


# ── ConversationMetadata full ────────────────────────────────────────


class TestConversationMetadataFull:
    def test_all_fields(self):
        now = datetime.now(UTC)
        md = ConversationMetadata(
            conversation_id='c1',
            title='Full Test',
            selected_repository='org/repo',
            user_id='user1',
            selected_branch='main',
            vcs_provider=ProviderType.ENTERPRISE_SSO,
            last_updated_at=now,
            trigger=ConversationTrigger.GUI,
            pr_number=[10, 20],
            created_at=now,
            llm_model='gpt-4',
            accumulated_cost=1.5,
            prompt_tokens=100,
            completion_tokens=200,
            total_tokens=300,
            name='Custom',
        )
        assert md.selected_repository == 'org/repo'
        assert md.user_id == 'user1'
        assert md.vcs_provider == ProviderType.ENTERPRISE_SSO
        assert md.trigger == ConversationTrigger.GUI
        assert md.pr_number == [10, 20]
        assert md.accumulated_cost == 1.5
        assert md.total_tokens == 300
