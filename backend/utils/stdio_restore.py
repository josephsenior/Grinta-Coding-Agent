"""Restore real stdio for subprocess/tmux while the TUI owns sys.stdout."""

from __future__ import annotations

import sys
from contextlib import contextmanager
from typing import IO, Iterator, cast


def _stream_has_encoding(stream: object) -> bool:
    return getattr(stream, 'encoding', None) is not None


class _StdioEncodingProxy:
    """Expose ``.encoding`` on Textual ``_PrintCapture`` streams for subprocess."""

    def __init__(self, inner: IO[str], *, encoding: str = 'utf-8') -> None:
        self._inner = inner
        self.encoding = encoding
        self.errors = 'replace'

    def write(self, data: str) -> int:
        return self._inner.write(data)

    def flush(self) -> None:
        self._inner.flush()

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)


def _with_encoding(stream: IO[str]) -> IO[str]:
    if _stream_has_encoding(stream):
        return stream
    return cast(IO[str], _StdioEncodingProxy(stream))


@contextmanager
def real_stdio_for_subprocess() -> Iterator[None]:
    """Make ``sys.stdout`` / ``sys.stderr`` subprocess-safe under the Textual TUI.

    Textual replaces ``sys.stdout`` (and often ``sys.__stdout__``) with
    ``_PrintCapture``, which lacks ``.encoding``. libtmux/subprocess only need
    that attribute; redirecting to ``/dev/tty`` can deadlock tmux while the TUI
    owns the terminal.
    """
    saved_stdout = sys.stdout
    saved_stderr = sys.stderr
    try:
        sys.stdout = _with_encoding(saved_stdout)
        sys.stderr = _with_encoding(saved_stderr)
        yield
    finally:
        sys.stdout = saved_stdout
        sys.stderr = saved_stderr
