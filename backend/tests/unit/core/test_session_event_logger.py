"""Tests for unified session.jsonl event logger."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.core.logging.session_event_logger import (
    bind_session_event_logger,
    close_session_event_logger,
    emit_session_event,
    is_noise_message,
)


@pytest.fixture(autouse=True)
def _reset_session_logger() -> None:
    close_session_event_logger()
    yield
    close_session_event_logger()


def test_is_noise_message_filters_streaming_chunks() -> None:
    assert is_noise_message('on_event received StreamingChunkAction (id=1)')
    assert is_noise_message('[streaming-dbg] chunk')
    assert not is_noise_message('Setting agent state from RUNNING to FINISHED')


def test_emit_writes_jsonl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        'backend.core.logging.session_event_logger.LOG_TO_FILE', True
    )
    bind_session_event_logger('sess-1', str(tmp_path), workspace_segment='ws-seg')
    emit_session_event('USER_TURN', {'text': 'hello'})
    lines = [
        line
        for line in (tmp_path / 'session.jsonl')
        .read_text(encoding='utf-8')
        .splitlines()
        if line.strip()
    ]
    assert len(lines) >= 1
    record = json.loads(lines[-1])
    assert record['event'] == 'USER_TURN'
    assert record['payload']['text'] == 'hello'
    assert record['session_id'] == 'sess-1'
    assert record['workspace'] == 'ws-seg'


def test_wire_events_respect_grinta_log_wire(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        'backend.core.logging.session_event_logger.LOG_TO_FILE', True
    )
    bind_session_event_logger('sess-1', str(tmp_path))
    with patch(
        'backend.core.logging.session_event_logger.wire_log_enabled',
        return_value=False,
    ):
        emit_session_event('WIRE_PROMPT', {'messages': []})
    emit_session_event('PROMPT_SHAPE', {'roles': {'user': 1}})
    events = [
        json.loads(line)['event']
        for line in (tmp_path / 'session.jsonl').read_text(encoding='utf-8').splitlines()
        if line.strip()
    ]
    assert 'WIRE_PROMPT' not in events
    assert 'PROMPT_SHAPE' in events


def test_bind_emits_session_start(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        'backend.core.logging.session_event_logger.LOG_TO_FILE', True
    )
    bind_session_event_logger('abc', str(tmp_path), workspace_segment='ws')
    events = [
        json.loads(line)['event']
        for line in (tmp_path / 'session.jsonl').read_text(encoding='utf-8').splitlines()
        if line.strip()
    ]
    assert events[0] == 'SESSION_START'


def test_wire_log_enabled_default_true() -> None:
    import backend.core.constants as constants_mod

    assert constants_mod.GRINTA_LOG_WIRE is True
