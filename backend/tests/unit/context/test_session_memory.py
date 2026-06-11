"""Tests for backend.context.session_memory."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.context.session_memory import (
    get_content_for_compaction,
    maybe_update,
    session_memory_exists,
)
from backend.ledger.action.message import MessageAction
from backend.ledger.event import EventSource


def _user(text: str, event_id: int) -> MessageAction:
    action = MessageAction(content=text)
    action.id = event_id
    action.source = EventSource.USER
    return action


def test_maybe_update_writes_session_memory_when_threshold_crossed(
    tmp_path, monkeypatch
):
    memory_path = tmp_path / 'session_memory.md'
    monkeypatch.setattr(
        'backend.context.session_memory._session_memory_path',
        lambda state=None: memory_path,
    )
    state = MagicMock()
    state.session_id = 'mem-test-session'
    state.extra_data = {}

    def _set_extra(key, value, source='test'):
        state.extra_data[key] = value

    state.set_extra = _set_extra
    events = [_user('x' * 5000, i) for i in range(1, 40)]

    with patch(
        'backend.context.session_memory.extract_snapshot',
        return_value={'decisions': ['use pipeline'], 'files_touched': {}},
    ):
        assert maybe_update(state, events) is True
    assert session_memory_exists()
    assert (
        'Session Memory' in get_content_for_compaction()
        or 'pipeline' in get_content_for_compaction()
    )
