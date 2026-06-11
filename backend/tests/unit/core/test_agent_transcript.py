"""Tests for backend.core.agent_transcript."""

from __future__ import annotations

from backend.core.agent_transcript import (
    bind_agent_transcript,
    close_agent_transcript,
    record_agent_message,
    record_stream_final,
    record_user_message,
)
from backend.ledger import EventSource
from backend.ledger.action.message import MessageAction, StreamingChunkAction
from backend.orchestration.services.event_router_service import EventRouterService


def test_transcript_writes_user_stream_and_agent_message(tmp_path):
    bind_agent_transcript(str(tmp_path))
    record_user_message('fix tests', event_id=1)
    record_stream_final(
        'Reading test file now.',
        thinking='plan the fix',
        event_id=5,
    )
    record_agent_message('Done.', event_id=9, final_response=True)
    close_agent_transcript()

    text = (tmp_path / 'agent_transcript.log').read_text(encoding='utf-8')
    assert 'USER (event 1)' in text
    assert 'fix tests' in text
    assert 'AGENT stream-final (event 5)' in text
    assert 'Reading test file now.' in text
    assert '[thinking]' in text
    assert 'plan the fix' in text
    assert 'AGENT final-response (event 9)' in text
    assert 'Done.' in text


def test_transcript_dedupes_same_event_id_only(tmp_path):
    bind_agent_transcript(str(tmp_path))
    record_stream_final('same text', event_id=1)
    record_stream_final('same text', event_id=1)
    record_stream_final('same text', event_id=2)
    close_agent_transcript()
    text = (tmp_path / 'agent_transcript.log').read_text(encoding='utf-8')
    assert text.count('same text') == 2
    assert 'event 1)' in text
    assert 'event 2)' in text


def test_transcript_records_tool_step_messages(tmp_path):
    bind_agent_transcript(str(tmp_path))
    record_agent_message(
        'Creating raftkv/node.py',
        thought='plan the node loop',
        event_id=10,
        tool_step=True,
    )
    record_stream_final(
        '',
        thinking='inspect existing files first',
        event_id=11,
        suppress_live_response=True,
    )
    close_agent_transcript()
    text = (tmp_path / 'agent_transcript.log').read_text(encoding='utf-8')
    assert 'AGENT step (tools)' in text
    assert 'Creating raftkv/node.py' in text
    assert 'AGENT step (stream+tools)' in text
    assert 'inspect existing files first' in text


def test_event_router_records_transcript_only_agent_message(tmp_path):
    bind_agent_transcript(str(tmp_path))

    class _Ctrl:
        state_tracker = None

    router = EventRouterService.__new__(EventRouterService)
    router._ctrl = _Ctrl()  # type: ignore[attr-defined]

    agent = MessageAction(
        content='I will create the package layout.', transcript_only=True
    )
    agent.source = EventSource.AGENT
    agent.id = 7
    router._record_agent_transcript(agent)

    close_agent_transcript()
    text = (tmp_path / 'agent_transcript.log').read_text(encoding='utf-8')
    assert 'AGENT step (tools)' in text
    assert 'package layout' in text


def test_event_router_records_transcript(tmp_path, monkeypatch):
    bind_agent_transcript(str(tmp_path))

    class _Ctrl:
        state_tracker = None

    router = EventRouterService.__new__(EventRouterService)
    router._ctrl = _Ctrl()  # type: ignore[attr-defined]

    stream = StreamingChunkAction(
        accumulated='Hello from the model.',
        is_final=True,
        thinking_accumulated='reasoning',
    )
    stream.id = 42
    router._record_agent_transcript(stream)

    user = MessageAction(content='hi')
    user.source = EventSource.USER
    user.id = 1
    router._record_agent_transcript(user)

    close_agent_transcript()
    text = (tmp_path / 'agent_transcript.log').read_text(encoding='utf-8')
    assert 'Hello from the model.' in text
    assert 'hi' in text
