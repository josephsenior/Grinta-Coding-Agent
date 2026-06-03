"""DAP logging helpers — forbidden LogRecord keys + structured DAP logger.

Extracted from backend/execution/debugger.py to keep the parent module
under the per-file LOC budget. These are pure functions used by all DAP
classes to log trace events to app.log.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.core.logger import app_logger as logger

_LOGRECORD_EXTRA_FORBIDDEN: frozenset[str] | None = None


def _logrecord_keys_that_forbid_extra() -> frozenset[str]:
    """Names that cannot appear in ``Logger.log(..., extra=...)`` without raising.

    ``logging.Logger.makeRecord`` rejects any ``extra`` key that already exists on
    ``LogRecord`` (see CPython ``logging/__init__.py``). A collision raises
    ``KeyError`` and the log line is never emitted — easy to mistake for “logging
    is broken” when structured fields reuse names like ``filename``, ``module``, or
    ``process``.
    """
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
    """Structured DAP trace for ``app.log`` (JSON formatter picks up ``extra``).

    INFO is promoted to WARNING so traces survive ``LOG_LEVEL=WARNING`` and match
    how operators grep ``app.log`` for hangs (startup lines are never silently dropped).
    """
    forbidden = _logrecord_keys_that_forbid_extra()
    extra: dict[str, Any] = {'msg_type': msg_type}
    for key, val in fields.items():
        if val is None:
            continue
        safe_key = key if key not in forbidden else f'dap_{key}'
        extra[safe_key] = val
    effective = logging.WARNING if level == logging.INFO else level
    # Prefix so plain-text grep on app.log ``message`` finds traces even if JSON
    # formatting or tooling only surfaces the main record message.
    logger.log(effective, f'[{msg_type}] {message}', extra=extra)
