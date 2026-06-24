"""Human-readable transcript of agent and user messages per session.

Writes ``agent_transcript.log`` alongside ``app.log`` so operators can read
what the agent actually said without wading through StreamingChunkAction ids.
"""

from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from typing import TextIO

_LOCK = threading.Lock()
_TRANSCRIPT_PATH: str | None = None
_TRANSCRIPT_STREAM: TextIO | None = None
_LAST_WRITTEN_KEYS: set[tuple[str, int | None]] = set()
_LAST_STREAM_FINAL_CONTENT: str = ''


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')


def _event_suffix(event_id: int | None) -> str:
    return f' (event {event_id})' if event_id is not None else ''


def bind_agent_transcript(session_log_dir: str) -> None:
    """Open or rotate ``agent_transcript.log`` for the active session."""
    global \
        _TRANSCRIPT_PATH, \
        _TRANSCRIPT_STREAM, \
        _LAST_WRITTEN_KEYS, \
        _LAST_STREAM_FINAL_CONTENT
    path = os.path.join(session_log_dir, 'agent_transcript.log')
    with _LOCK:
        close_agent_transcript_unlocked()
        os.makedirs(session_log_dir, exist_ok=True)
        stream = open(path, 'a', encoding='utf-8', buffering=1)  # noqa: SIM115
        if os.path.getsize(path) == stream.tell():
            stream.write(
                '# Grinta agent transcript — user prompts and agent responses\n'
                '# One block per user message and per agent step (text, thinking, tools).\n\n'
            )
            stream.flush()
        _TRANSCRIPT_PATH = path
        _TRANSCRIPT_STREAM = stream
        _LAST_WRITTEN_KEYS = set()
        _LAST_STREAM_FINAL_CONTENT = ''


def close_agent_transcript_unlocked() -> None:
    global \
        _TRANSCRIPT_PATH, \
        _TRANSCRIPT_STREAM, \
        _LAST_WRITTEN_KEYS, \
        _LAST_STREAM_FINAL_CONTENT
    if _TRANSCRIPT_STREAM is not None:
        try:
            _TRANSCRIPT_STREAM.flush()
            _TRANSCRIPT_STREAM.close()
        except Exception:
            pass
    _TRANSCRIPT_STREAM = None
    _TRANSCRIPT_PATH = None
    _LAST_WRITTEN_KEYS = set()
    _LAST_STREAM_FINAL_CONTENT = ''


def _normalize_transcript_content(text: str) -> str:
    from backend.cli.event_rendering.text_utils import sanitize_visible_transcript_text

    return sanitize_visible_transcript_text(text or '').strip()


def close_agent_transcript() -> None:
    with _LOCK:
        close_agent_transcript_unlocked()


def _write_block(kind: str, body: str, *, event_id: int | None = None) -> None:
    text = body.strip()
    if not text:
        return
    dedupe_key = (kind, event_id)
    with _LOCK:
        if _TRANSCRIPT_STREAM is None:
            return
        if dedupe_key in _LAST_WRITTEN_KEYS:
            return
        _LAST_WRITTEN_KEYS.add(dedupe_key)
        header = f'{"=" * 80}\n{_now_stamp()} | {kind}{_event_suffix(event_id)}\n'
        _TRANSCRIPT_STREAM.write(f'{header}{"-" * 80}\n{text}\n\n')
        _TRANSCRIPT_STREAM.flush()


def record_user_message(content: str, *, event_id: int | None = None) -> None:
    global _LAST_STREAM_FINAL_CONTENT
    with _LOCK:
        _LAST_STREAM_FINAL_CONTENT = ''
    _write_block('USER', content, event_id=event_id)


def record_agent_message(
    content: str,
    *,
    thought: str = '',
    event_id: int | None = None,
    final_response: bool = False,
    tool_step: bool = False,
) -> None:
    global _LAST_STREAM_FINAL_CONTENT
    normalized_content = _normalize_transcript_content(content)
    if final_response and normalized_content:
        with _LOCK:
            if normalized_content == _LAST_STREAM_FINAL_CONTENT:
                _LAST_STREAM_FINAL_CONTENT = ''
                return
    parts: list[str] = []
    if content.strip():
        parts.append(content.strip())
    if thought.strip():
        parts.append(f'[thinking]\n{thought.strip()}')
    if not parts:
        return
    if final_response:
        label = 'AGENT final-response'
    elif tool_step:
        label = 'AGENT step (tools)'
    else:
        label = 'AGENT message'
    _write_block(label, '\n\n'.join(parts), event_id=event_id)


def record_stream_final(
    accumulated: str,
    *,
    thinking: str = '',
    event_id: int | None = None,
    suppress_live_response: bool = False,
) -> None:
    global _LAST_STREAM_FINAL_CONTENT
    normalized_accumulated = _normalize_transcript_content(accumulated)
    if normalized_accumulated:
        with _LOCK:
            _LAST_STREAM_FINAL_CONTENT = normalized_accumulated
    parts: list[str] = []
    if accumulated.strip():
        parts.append(accumulated.strip())
    if thinking.strip():
        parts.append(f'[thinking]\n{thinking.strip()}')
    if not parts:
        return
    label = (
        'AGENT step (stream+tools)'
        if suppress_live_response and not accumulated.strip()
        else 'AGENT stream-final'
    )
    _write_block(label, '\n\n'.join(parts), event_id=event_id)


def record_think_action(thought: str, *, event_id: int | None = None) -> None:
    if not thought.strip():
        return
    _write_block('AGENT think', thought.strip(), event_id=event_id)
