"""Restore real stdio for subprocess/tmux while the TUI owns sys.stdout."""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from typing import IO, Iterator, TextIO


def _stream_has_encoding(stream: object) -> bool:
    return getattr(stream, 'encoding', None) is not None


def _posix_tty_stream() -> TextIO | None:
    if os.name != 'posix':
        return None
    try:
        stream = open('/dev/tty', 'w', encoding='utf-8', errors='replace')
    except OSError:
        return None
    if _stream_has_encoding(stream):
        return stream
    stream.close()
    return None


def _fd_stream(fd: int) -> TextIO | None:
    try:
        stream = os.fdopen(fd, 'w', encoding='utf-8', errors='replace', closefd=False)
    except OSError:
        return None
    if _stream_has_encoding(stream):
        return stream
    return None


def _resolve_stdio_streams() -> tuple[IO[str], IO[str], TextIO | None]:
    """Return stdout/stderr streams subprocess helpers can read encoding from."""
    tty = _posix_tty_stream()
    if tty is not None:
        return tty, tty, tty

    stdout = getattr(sys, '__stdout__', None)
    if stdout is not None and _stream_has_encoding(stdout):
        out: IO[str] = stdout
    else:
        fd_out = _fd_stream(1)
        if fd_out is None:
            raise RuntimeError(
                'No stdio stream with encoding available for subprocess'
            )
        out = fd_out

    stderr = getattr(sys, '__stderr__', None)
    if stderr is not None and _stream_has_encoding(stderr):
        err: IO[str] = stderr
    else:
        fd_err = _fd_stream(2)
        err = fd_err if fd_err is not None else out

    return out, err, None


@contextmanager
def real_stdio_for_subprocess() -> Iterator[None]:
    """Point sys.stdout/stderr at real text streams for subprocess helpers.

    Textual replaces ``sys.stdout`` (and often ``sys.__stdout__``) with
    ``_PrintCapture``, which lacks ``.encoding``. libtmux/subprocess expect a
    real text stream during shell session startup.
    """
    saved_stdout = sys.stdout
    saved_stderr = sys.stderr
    tty_stream: TextIO | None = None
    try:
        real_out, real_err, tty_stream = _resolve_stdio_streams()
        sys.stdout = real_out
        sys.stderr = real_err
        yield
    finally:
        sys.stdout = saved_stdout
        sys.stderr = saved_stderr
        if tty_stream is not None:
            try:
                tty_stream.close()
            except OSError:
                pass
