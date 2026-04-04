"""Tests for backend.persistence.data_models.conversation_template — Template models."""

from __future__ import annotations

import pytest

from backend.persistence.data_models.conversation_template import (
    ConversationTemplate,
    CreateTemplateRequest,
    TemplateCategory,
    UpdateTemplateRequest,
)

# ── TemplateCategory ─────────────────────────────────────────────────


class TestTemplateCategory:
    def test_all_values(self):
        expected = {
            'debug',
            'refactor',
            'document',
            'test',
            'review',
            'explain',
            'optimize',
            'fix_bug',
            'add_feature',
            'custom',
        }
        actual = {c.value for c in TemplateCategory}
        assert actual == expected

    def test_count(self):
        assert len(TemplateCategory) == 10


# ── ConversationTemplate ─────────────────────────────────────────────


class TestConversationTemplate:
    def test_valid(self):
        t = ConversationTemplate(
            id='t1',
            title='Debug template',
            prompt='Debug this code',
        )
        assert t.id == 't1'
        assert t.title == 'Debug template'
        assert t.category == TemplateCategory.CUSTOM
        assert t.is_favorite is False
        assert t.usage_count == 0
        assert t.metadata == {}
        assert t.description is None
        assert t.icon is None

    def test_full(self):
        t = ConversationTemplate(
            id='t2',
            title='Refactor',
            description='Refactor code for readability',
            category=TemplateCategory.REFACTOR,
            prompt='Refactor the following',
            icon='wrench',
            is_favorite=True,
            usage_count=5,
            metadata={'key': 'val'},
        )
        assert t.category == TemplateCategory.REFACTOR
        assert t.is_favorite is True
        assert t.usage_count == 5
        assert t.metadata == {'key': 'val'}

    def test_empty_id_rejected(self):
        with pytest.raises(Exception):
            ConversationTemplate(id='', title='T', prompt='P')

    def test_empty_title_rejected(self):
        with pytest.raises(Exception):
            ConversationTemplate(id='x', title='', prompt='P')

    def test_empty_prompt_rejected(self):
        with pytest.raises(Exception):
            ConversationTemplate(id='x', title='T', prompt='')

    def test_usage_count_ge_0(self):
        with pytest.raises(Exception):
            ConversationTemplate(id='x', title='T', prompt='P', usage_count=-1)

    def test_title_max_length(self):
        with pytest.raises(Exception):
            ConversationTemplate(id='x', title='A' * 201, prompt='P')


# ── CreateTemplateRequest ────────────────────────────────────────────


class TestCreateTemplateRequest:
    def test_valid(self):
        r = CreateTemplateRequest(title='New', prompt='Do something')
        assert r.title == 'New'
        assert r.category == TemplateCategory.CUSTOM
        assert r.is_favorite is False

    def test_empty_title_rejected(self):
        with pytest.raises(Exception):
            CreateTemplateRequest(title='', prompt='P')

    def test_empty_prompt_rejected(self):
        with pytest.raises(Exception):
            CreateTemplateRequest(title='T', prompt='')

    def test_with_all_fields(self):
        r = CreateTemplateRequest(
            title='Debug',
            description='Debug helper',
            category=TemplateCategory.DEBUG,
            prompt='Debug this',
            icon='bug',
            is_favorite=True,
        )
        assert r.category == TemplateCategory.DEBUG
        assert r.icon == 'bug'


# ── UpdateTemplateRequest ────────────────────────────────────────────


class TestUpdateTemplateRequest:
    def test_all_none(self):
        r = UpdateTemplateRequest()
        assert r.title is None
        assert r.description is None
        assert r.category is None
        assert r.prompt is None
        assert r.icon is None
        assert r.is_favorite is None

    def test_partial_update(self):
        r = UpdateTemplateRequest(title='Updated', is_favorite=True)
        assert r.title == 'Updated'
        assert r.is_favorite is True
        assert r.prompt is None
