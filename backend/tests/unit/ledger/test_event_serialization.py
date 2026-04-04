"""Tests for backend.ledger.serialization.event – truncation and serialization helpers."""

from __future__ import annotations

import pytest

from backend.ledger.action import MessageAction, NullAction
from backend.ledger.event import EventSource
from backend.ledger.observation import ErrorObservation, LspQueryObservation
from backend.ledger.serialization.event import (
    event_from_dict,
    event_to_dict,
    event_to_trajectory,
    truncate_content,
)

# ── truncate_content ─────────────────────────────────────────────────


class TestTruncateContent:
    def test_no_truncation_when_none(self):
        assert truncate_content('hello world', None) == 'hello world'

    def test_no_truncation_when_short(self):
        assert truncate_content('abc', 100) == 'abc'

    def test_truncates_long_content(self):
        content = 'x' * 200
        result = truncate_content(content, 50)
        assert len(result) < 200
        assert 'truncated' in result.lower()

    def test_negative_max_returns_original(self):
        assert truncate_content('hello', -1) == 'hello'

    def test_exact_length_no_truncation(self):
        content = 'a' * 100
        assert truncate_content(content, 100) == content

    def test_truncation_preserves_start_and_end(self):
        content = 'START' + 'x' * 200 + 'END'
        result = truncate_content(content, 50)
        assert result.startswith('START')
        assert result.endswith('END')


# ── event_from_dict ──────────────────────────────────────────────────


class TestEventFromDict:
    def test_action_event(self):
        data = {
            'action': 'message',
            'args': {'content': 'hello', 'image_urls': [], 'wait_for_response': False},
            'source': 'user',
        }
        evt = event_from_dict(data)
        assert isinstance(evt, MessageAction)

    def test_observation_event(self):
        data = {
            'observation': 'error',
            'content': 'something broke',
            'extras': {'error_id': 'ERR_1'},
        }
        evt = event_from_dict(data)
        assert isinstance(evt, ErrorObservation)

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match='Unknown event type'):
            event_from_dict({'neither': True})


# ── event_to_dict ────────────────────────────────────────────────────


class TestEventToDict:
    def test_action_roundtrip(self):
        action = MessageAction(content='hi')
        action._source = EventSource.USER
        d = event_to_dict(action)
        assert d['action'] == 'message'
        assert d.get('source') == 'user'
        assert d['args']['content'] == 'hi'

    def test_observation_roundtrip(self):
        obs = ErrorObservation(content='err msg')
        obs._source = EventSource.ENVIRONMENT
        d = event_to_dict(obs)
        assert d['observation'] == 'error'
        assert d['content'] == 'err msg'

    def test_lsp_observation_serializes_with_type_and_available_message(self):
        obs = LspQueryObservation(content='Found 1 result(s):', available=True)
        obs._source = EventSource.AGENT

        d = event_to_dict(obs)

        assert d['observation'] == 'lsp_query_result'
        assert d['content'] == 'Found 1 result(s):'
        assert d['message'] == 'LSP query completed.'
        assert d['extras']['available'] is True

    def test_lsp_observation_serializes_unavailable_message(self):
        obs = LspQueryObservation(content='LSP is not available', available=False)
        obs._source = EventSource.AGENT

        d = event_to_dict(obs)

        assert d['observation'] == 'lsp_query_result'
        assert 'LSP unavailable' in d['message']
        assert d['extras']['available'] is False


# ── event_to_trajectory ─────────────────────────────────────────────


class TestEventToTrajectory:
    def test_null_action_returns_none(self):
        action = NullAction()
        action._source = EventSource.AGENT
        result = event_to_trajectory(action)
        assert result is None

    def test_action_event_creates_trajectory(self):
        action = MessageAction(content='task')
        action._source = EventSource.USER
        result = event_to_trajectory(action)
        assert result is not None
        assert result['action'] == 'message'

    def test_excludes_screenshots_by_default(self):
        obs = ErrorObservation(content='err')
        obs._source = EventSource.ENVIRONMENT
        result = event_to_trajectory(obs, include_screenshots=False)
        assert result is not None
        extras = result.get('extras', {})
        assert 'screenshot' not in extras
        assert 'set_of_marks' not in extras
