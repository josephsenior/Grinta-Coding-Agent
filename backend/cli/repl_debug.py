"""Diagnostic helper that writes to a file to avoid stderr buffering issues."""
from __future__ import annotations

import os

_DEBUG_FILE = os.path.join(os.environ.get('TEMP', '/tmp'), 'grinta_debug.log')

def debug(msg: str) -> None:
    try:
        with open(_DEBUG_FILE, 'a', encoding='utf-8') as f:
            f.write(f'{msg}\n')
    except Exception:
        pass