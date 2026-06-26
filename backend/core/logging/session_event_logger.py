"""Unified session.jsonl event logger — single write path for session observability."""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from backend.core.constants import GRINTA_LOG_WIRE, LOG_LEVEL, LOG_TO_FILE
from backend.core.logging.session_context import (
    capture_context_snapshot,
    clear_runtime_context,
    consume_context_change,
    register_runtime_context,
)

SESSION_LOG_FILENAME = 'session.jsonl'
TRANSCRIPT_FILENAME = 'session.txt'
AUDIT_FILENAME = 'session.audit.txt'

WIRE_EVENTS = frozenset({'WIRE_PROMPT', 'WIRE_RESPONSE'})

NOISE_MESSAGE_PATTERNS = (
    re.compile(r'on_event received StreamingChunkAction\b'),
    re.compile(r'\[streaming-dbg\]'),
    re.compile(r'\[TUI\] _dispatch_to_agent: poll #'),
    re.compile(r'_dispatch_to_agent: \d+ consecutive polls'),
    re.compile(r'dispatching via run_or_schedule$'),
    re.compile(r'StreamingChunkAction'),
)

_LOCK = threading.Lock()
_STREAM: TextIO | None = None
_SESSION_DIR: str | None = None
_SESSION_ID: str | None = None
_WORKSPACE_SEGMENT: str | None = None
_RUNTIME_DEBUG = LOG_LEVEL.upper() == 'DEBUG'


def wire_log_enabled() -> bool:
    return GRINTA_LOG_WIRE


def session_log_path(log_dir: str | Path | None = None) -> Path:
    base = Path(log_dir or _SESSION_DIR or '')
    return base / SESSION_LOG_FILENAME


def is_noise_message(message: str) -> bool:
    return any(p.search(message) for p in NOISE_MESSAGE_PATTERNS)


def _json_default(obj: Any) -> Any:
    if hasattr(obj, 'model_dump'):
        return obj.model_dump()
    if hasattr(obj, 'to_dict'):
        return obj.to_dict()
    if hasattr(obj, '__dict__'):
        return {k: v for k, v in obj.__dict__.items() if not k.startswith('_')}
    return str(obj)


class SessionEventLogger:
    """Thread-safe writer for ``session.jsonl``."""

    def __init__(self) -> None:
        self._stream: TextIO | None = None
        self._session_dir: str | None = None
        self._session_id: str | None = None
        self._workspace: str | None = None

    @property
    def is_bound(self) -> bool:
        return self._stream is not None

    @property
    def session_dir(self) -> str | None:
        return self._session_dir

    def bind(
        self,
        session_id: str,
        log_dir: str,
        *,
        workspace_segment: str | None = None,
    ) -> None:
        self.close()
        os.makedirs(log_dir, exist_ok=True)
        path = os.path.join(log_dir, SESSION_LOG_FILENAME)
        stream = open(path, 'a', encoding='utf-8', buffering=1)  # noqa: SIM115
        self._stream = stream
        self._session_dir = log_dir
        self._session_id = session_id
        self._workspace = workspace_segment
        global _STREAM, _SESSION_DIR, _SESSION_ID, _WORKSPACE_SEGMENT
        with _LOCK:
            _STREAM = stream
            _SESSION_DIR = log_dir
            _SESSION_ID = session_id
            _WORKSPACE_SEGMENT = workspace_segment

    def close(self) -> None:
        global _STREAM, _SESSION_DIR, _SESSION_ID, _WORKSPACE_SEGMENT
        if self._stream is not None:
            try:
                self._stream.flush()
                self._stream.close()
            except Exception:
                pass
        self._stream = None
        self._session_dir = None
        with _LOCK:
            if _STREAM is self._stream:
                _STREAM = None
                _SESSION_DIR = None
                _SESSION_ID = None
                _WORKSPACE_SEGMENT = None

    def flush(self) -> None:
        if self._stream is not None:
            self._stream.flush()

    def emit(
        self,
        event: str,
        payload: dict[str, Any],
        *,
        level: str = 'INFO',
        ctx: dict[str, Any] | None = None,
    ) -> None:
        if not LOG_TO_FILE or self._stream is None:
            return
        if event in WIRE_EVENTS and not wire_log_enabled():
            return

        envelope_ctx = dict(ctx or capture_context_snapshot())
        record = {
            'ts': datetime.now(UTC).isoformat(),
            'level': level,
            'event': event,
            'session_id': self._session_id,
            'workspace': self._workspace,
            'ctx': envelope_ctx,
            'payload': payload,
        }
        line = json.dumps(record, default=_json_default, ensure_ascii=False)
        with _LOCK:
            if self._stream is None:
                return
            self._stream.write(line + '\n')
            self._stream.flush()

        if event == 'SESSION_CONTEXT':
            return
        changed = consume_context_change()
        if changed is not None and event != 'SESSION_START':
            self.emit('SESSION_CONTEXT', changed, level='INFO')


_SESSION_LOGGER = SessionEventLogger()


def get_session_event_logger() -> SessionEventLogger:
    return _SESSION_LOGGER


def bind_session_event_logger(
    session_id: str,
    log_dir: str,
    *,
    workspace_segment: str | None = None,
    startup_payload: dict[str, Any] | None = None,
) -> None:
    _SESSION_LOGGER.bind(session_id, log_dir, workspace_segment=workspace_segment)
    payload = dict(startup_payload or {})
    payload.setdefault('session_id', session_id)
    payload.setdefault('platform', sys.platform)
    _SESSION_LOGGER.emit('SESSION_START', payload, level='INFO')
    full_ctx = consume_context_change()
    if full_ctx:
        _SESSION_LOGGER.emit('SESSION_CONTEXT', full_ctx, level='INFO')


def close_session_event_logger() -> None:
    _SESSION_LOGGER.close()
    clear_runtime_context()


def emit_session_event(
    event: str,
    payload: dict[str, Any],
    *,
    level: str = 'INFO',
    ctx: dict[str, Any] | None = None,
) -> None:
    _SESSION_LOGGER.emit(event, payload, level=level, ctx=ctx)


def emit_session_context_if_changed() -> None:
    changed = consume_context_change()
    if changed is not None:
        emit_session_event('SESSION_CONTEXT', changed, level='INFO')


class SessionEventLogHandler(logging.Handler):
    """Route ``app`` logger records into ``session.jsonl`` as RUNTIME/ISSUE/MCP."""

    def __init__(self, *, mcp_server: str | None = None) -> None:
        super().__init__()
        self.mcp_server = mcp_server

    def emit(self, record: logging.LogRecord) -> None:
        if not LOG_TO_FILE or not _SESSION_LOGGER.is_bound:
            return
        message = record.getMessage()
        if is_noise_message(message):
            return

        msg_type = getattr(record, 'msg_type', None)
        level = record.levelname
        payload: dict[str, Any] = {'message': message}
        if msg_type:
            payload['msg_type'] = msg_type
        for key in (
            'astep_id',
            'tool',
            'ok',
            'latency_ms',
            'action_id',
            'call_id',
            'observation',
            'server',
        ):
            val = getattr(record, key, None)
            if val is not None:
                payload[key] = val

        if self.mcp_server:
            emit_session_event(
                'MCP',
                {'server': self.mcp_server, 'line': message},
                level=level,
            )
            return

        if level in {'WARNING', 'ERROR', 'CRITICAL'}:
            if record.exc_info and record.exc_info[1]:
                payload['exc_type'] = type(record.exc_info[1]).__name__
                payload['exc_message'] = str(record.exc_info[1])
            emit_session_event('ISSUE', payload, level=level)
            return

        if not _RUNTIME_DEBUG and level == 'DEBUG':
            return

        emit_session_event('RUNTIME', payload, level=level)


__all__ = [
    'AUDIT_FILENAME',
    'SESSION_LOG_FILENAME',
    'TRANSCRIPT_FILENAME',
    'SessionEventLogHandler',
    'SessionEventLogger',
    'bind_session_event_logger',
    'close_session_event_logger',
    'emit_session_context_if_changed',
    'emit_session_event',
    'get_session_event_logger',
    'is_noise_message',
    'register_runtime_context',
    'session_log_path',
    'wire_log_enabled',
]
