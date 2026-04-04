"""Regression tests for fail-closed message serialization."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.engine.message_serializer import (
    MessageSerializationError,
    serialize_messages,
)


def test_serialize_messages_success():
    msg = MagicMock()
    msg.role = 'user'
    msg.serialize_model.return_value = {'role': 'user', 'content': 'hello'}
    out = serialize_messages([msg])
    assert out == [{'role': 'user', 'content': 'hello'}]


def test_serialize_messages_fail_closed(monkeypatch):
    msg = MagicMock()
    msg.role = 'user'
    msg.serialize_model.side_effect = RuntimeError('boom')
    monkeypatch.delenv('APP_DEGRADED_MESSAGE_SERIALIZATION', raising=False)
    with pytest.raises(MessageSerializationError):
        serialize_messages([msg])


def test_serialize_messages_degraded_mode(monkeypatch):
    msg = MagicMock()
    msg.role = 'user'
    msg.serialize_model.side_effect = ValueError('bad shape')
    chunk = MagicMock()
    chunk.text = 'fallback text'
    msg.content = [chunk]
    monkeypatch.setenv('APP_DEGRADED_MESSAGE_SERIALIZATION', '1')
    try:
        out = serialize_messages([msg])
    finally:
        monkeypatch.delenv('APP_DEGRADED_MESSAGE_SERIALIZATION', raising=False)
    assert out[0]['role'] == 'user'
    assert out[0]['content'] == 'fallback text'
