"""Diagnostic helper that writes to the app log dir to avoid stderr buffering issues."""

from __future__ import annotations

import os


def _log_path() -> str:
    """Return the path for the diag log file.

    Uses the application log directory when available, falling back to TEMP.
    """
    try:
        from backend.core.logger import get_log_dir

        log_dir = get_log_dir()
        os.makedirs(log_dir, exist_ok=True)
        return os.path.join(log_dir, 'grinta_diag.log')
    except Exception:
        return os.path.join(os.environ.get('TEMP', '/tmp'), 'grinta_diag.log')


def debug(msg: str) -> None:
    try:
        with open(_log_path(), 'a', encoding='utf-8') as f:
            f.write(f'{msg}\n')
    except Exception:
        pass
