"""Restore real stdio for subprocess/tmux while the TUI owns sys.stdout."""

from __future__ import annotations

import sys
from contextlib import contextmanager
from typing import Iterator


@contextmanager
def real_stdio_for_subprocess() -> Iterator[None]:
    """Point sys.stdout/stderr at the process streams for subprocess helpers.

    Textual replaces ``sys.stdout`` with ``_PrintCapture``, which lacks
    ``.encoding``. libtmux/subprocess expect a real text stream during shell
    session startup.
    """
    saved_stdout = sys.stdout
    saved_stderr = sys.stderr
    sys.stdout = getattr(sys, '__stdout__', saved_stdout)
    sys.stderr = getattr(sys, '__stderr__', saved_stderr)
    try:
        yield
    finally:
        sys.stdout = saved_stdout
        sys.stderr = saved_stderr
