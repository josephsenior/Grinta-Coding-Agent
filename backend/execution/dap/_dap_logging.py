"""DAP logging helpers — structured DAP events in session.jsonl."""

from __future__ import annotations

import logging
from typing import Any

from backend.core.logging.session_event_logger import emit_session_event

_LOGRECORD_EXTRA_FORBIDDEN: frozenset[str] | None = None


def _logrecord_keys_that_forbid_extra() -> frozenset[str]:
    """Names that cannot appear in ``Logger.log(..., extra=...)`` without raising."""
    global _LOGRECORD_EXTRA_FORBIDDEN
    if _LOGRECORD_EXTRA_FORBIDDEN is None:
        sample = logging.LogRecord(
            name='',
            level=logging.DEBUG,
            pathname='',
            lineno=0,
            msg='',
            args=(),
            exc_info=None,
        )
        _LOGRECORD_EXTRA_FORBIDDEN = frozenset(sample.__dict__) | frozenset(
            ('message', 'asctime')
        )
    return _LOGRECORD_EXTRA_FORBIDDEN


def _dap_log(
    level: int,
    message: str,
    *,
    msg_type: str,
    **fields: Any,
) -> None:
    """Structured DAP trace as session.jsonl DAP event."""
    forbidden = _logrecord_keys_that_forbid_extra()
    payload: dict[str, Any] = {'message': message, 'msg_type': msg_type}
    for key, val in fields.items():
        if val is None:
            continue
        safe_key = key if key not in forbidden else f'dap_{key}'
        payload[safe_key] = val
    level_name = logging.getLevelName(level)
    if isinstance(level_name, str):
        emit_level = level_name
    else:
        emit_level = 'INFO'
    emit_session_event('DAP', payload, level=emit_level)
