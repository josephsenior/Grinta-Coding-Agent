"""Tests for session.txt rendering from session.jsonl events."""

from __future__ import annotations

from backend.core.logging.session_log_renderer import render_session_transcript


def test_render_user_and_agent_steps() -> None:
    events = [
        {
            'ts': '2026-06-08T10:00:00.000Z',
            'event': 'USER_TURN',
            'payload': {'text': 'Fix the bug', 'event_id': 1},
        },
        {
            'ts': '2026-06-08T10:00:01.000Z',
            'event': 'AGENT_STEP',
            'payload': {
                'text': 'I will inspect the file.',
                'thinking': 'Need to read source first.',
                'event_id': 2,
                'final_response': True,
            },
        },
        {
            'ts': '2026-06-08T10:00:02.000Z',
            'event': 'TOOL_RESULT',
            'payload': {
                'tool': 'read_file',
                'ok': True,
                'preview': 'def foo(): pass',
                'latency_ms': 50,
            },
        },
    ]
    text = render_session_transcript(events)
    assert 'USER' in text
    assert 'Fix the bug' in text
    assert 'AGENT final-response' in text
    assert '[thinking]' in text
    assert 'TOOL read_file' in text


def test_render_skips_empty_user_turn() -> None:
    events = [
        {
            'ts': '2026-06-08T10:00:00.000Z',
            'event': 'USER_TURN',
            'payload': {'text': '   '},
        },
    ]
    text = render_session_transcript(events)
    assert 'USER' not in text
