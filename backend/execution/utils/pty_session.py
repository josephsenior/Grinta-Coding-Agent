"""OS-agnostic interactive terminal session primitive.

Backed by native pseudo-terminal APIs:

- POSIX (Linux / macOS): ``ptyprocess`` (``forkpty`` + ``termios``)
- Windows: ``pywinpty`` (ConPTY)

The session spawns a child process attached to a real PTY, runs a background
reader thread to drain output into a bounded, offset-stable buffer, and
exposes a small unified API for:

- writing input (lines, raw bytes, or named control sequences)
- reading full or incremental output
- resizing the terminal window
- waiting for termination / graceful close / force kill

Decoded PTY output is stored as ``str``. A small deterministic sanitizer strips
ANSI/OSC/DCS control sequences and common ConPTY orphan-parameter leaks before
text enters the buffer, while preserving newlines/tabs/carriage returns for
shell transcripts. It is designed to be wired into higher-level shell
abstractions (``UnifiedShellSession``, agent tools, REPL UI).
"""

from __future__ import annotations

import errno
import re
import shlex
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from backend.core.logger import app_logger as logger
from backend.core.os_capabilities import OS_CAPS

IS_WINDOWS = OS_CAPS.is_windows

DEFAULT_BUFFER_CHARS = 1_048_576
DEFAULT_READ_CHUNK = 4096
DEFAULT_DIMENSIONS: tuple[int, int] = (24, 80)
_MAX_SANITIZE_CARRY = 256

# Common terminal control sequences keyed by human-friendly aliases.
# Values are the literal characters written to the PTY.
CONTROL_SEQUENCES: dict[str, str] = {
    'c': '\x03',
    'ctrl-c': '\x03',
    'sigint': '\x03',
    'd': '\x04',
    'ctrl-d': '\x04',
    'eof': '\x04',
    'z': '\x1a',
    'ctrl-z': '\x1a',
    'sigtstp': '\x1a',
    'backslash': '\x1c',
    'ctrl-\\': '\x1c',
    'sigquit': '\x1c',
    'l': '\x0c',
    'ctrl-l': '\x0c',
    'u': '\x15',
    'ctrl-u': '\x15',
    'a': '\x01',
    'ctrl-a': '\x01',
    'e': '\x05',
    'ctrl-e': '\x05',
    'esc': '\x1b',
    'escape': '\x1b',
    'enter': '\r',
    'cr': '\r',
    'lf': '\n',
    'tab': '\t',
    'backspace': '\x7f',
    'space': ' ',
}


class PtyUnavailableError(RuntimeError):
    """Raised when the platform PTY backend cannot be imported or loaded."""


class InteractiveSessionError(RuntimeError):
    """Raised for misuse (write after close, invalid state, etc.)."""


def _is_token_boundary(text: str, idx: int) -> bool:
    """True when ``idx`` is at start or follows a non-alnum separator."""
    if idx <= 0:
        return True
    return not text[idx - 1].isalnum()


_ORPHAN_PARAM_TOKEN_RE = re.compile(r'\[?\d+(?:;\d+){2,}[OI]?_')
_ORPHAN_PARAM_PREFIX_RE = re.compile(r'\[?\d+(?:;\d+){2,}[OI]?$')


def _parse_orphan_param_token(text: str, start: int) -> int | None:
    """Parse one leaked ConPTY-ish token like ``[17;29;0;1;40;1_``."""
    if match := _ORPHAN_PARAM_TOKEN_RE.match(text, start):
        return match.end()
    if _ORPHAN_PARAM_PREFIX_RE.fullmatch(text[start:]):
        return -1
    return None


def _consume_csi_escape(src: str, start: int) -> tuple[int, str | None]:
    j = start + 2
    n = len(src)
    while j < n and 0x30 <= ord(src[j]) <= 0x3F:
        j += 1
    while j < n and 0x20 <= ord(src[j]) <= 0x2F:
        j += 1
    if j >= n:
        return start, src[start:]
    if 0x40 <= ord(src[j]) <= 0x7E:
        return j + 1, None
    return start + 1, None


def _consume_osc_escape(src: str, start: int) -> tuple[int, str | None]:
    j = start + 2
    n = len(src)
    while j < n:
        if src[j] == '\x07':
            return j + 1, None
        if src[j] == '\x1b':
            if j + 1 >= n:
                return start, src[start:]
            if src[j + 1] == '\\':
                return j + 2, None
        j += 1
    return start, src[start:]


def _consume_string_escape(src: str, start: int) -> tuple[int, str | None]:
    j = start + 2
    n = len(src)
    while j < n:
        if src[j] == '\x1b':
            if j + 1 >= n:
                return start, src[start:]
            if src[j + 1] == '\\':
                return j + 2, None
        j += 1
    return start, src[start:]


def _consume_escape_sequence(src: str, start: int) -> tuple[int, str | None]:
    if start + 1 >= len(src):
        return start, src[start:]

    nxt = src[start + 1]
    if nxt == '[':
        return _consume_csi_escape(src, start)
    if nxt == ']':
        return _consume_osc_escape(src, start)
    if nxt in ('P', 'X', '^', '_'):
        return _consume_string_escape(src, start)
    if '@' <= nxt <= '_':
        return start + 2, None
    return start + 1, None


def _should_drop_c0_control(ch: str, code: int) -> bool:
    return code < 0x20 and ch not in ('\n', '\r', '\t')


def _consume_orphan_param_chunks(src: str, start: int) -> tuple[int | None, str | None]:
    ch = src[start]
    if not (ch.isdigit() or ch == '[') or not _is_token_boundary(src, start):
        return None, None

    j = start
    token_count = 0
    while True:
        end = _parse_orphan_param_token(src, j)
        if end is None:
            return (j, None) if token_count >= 2 else (None, None)
        if end < 0:
            if token_count > 0:
                return None, src[start:]
            return None, None
        token_count += 1
        j = end


def _consume_escape_step(src: str, start: int) -> tuple[int, str | None] | None:
    if src[start] != '\x1b':
        return None
    return _consume_escape_sequence(src, start)


def _consume_orphan_step(src: str, start: int) -> tuple[int, str | None] | None:
    next_index, carry_out = _consume_orphan_param_chunks(src, start)
    if next_index is None and carry_out is None:
        return None
    return start if next_index is None else next_index, carry_out


def _consume_sanitizer_step(
    src: str, start: int
) -> tuple[int, str | None, str | None]:
    escape_result = _consume_escape_step(src, start)
    if escape_result is not None:
        next_index, carry_out = escape_result
        return next_index, carry_out, None

    ch = src[start]
    if _should_drop_c0_control(ch, ord(ch)):
        return start + 1, None, None

    orphan_result = _consume_orphan_step(src, start)
    if orphan_result is not None:
        next_index, carry_out = orphan_result
        return next_index, carry_out, None

    return start + 1, None, ch


def _finalize_sanitized_chunk(src: str, out: list[str]) -> tuple[str, str]:
    carry_out = ''
    if src and src[-1] == '\x1b':
        if out and out[-1] == '\x1b':
            out.pop()
        carry_out = '\x1b'
    if len(carry_out) > _MAX_SANITIZE_CARRY:
        carry_out = carry_out[-_MAX_SANITIZE_CARRY:]
    return ''.join(out), carry_out


def _sanitize_terminal_text_chunk(
    text: str,
    carry: str = '',
) -> tuple[str, str]:
    """Remove terminal control traffic and leaked orphan parameter chunks.

    Returns ``(clean_text, next_carry)`` where ``next_carry`` stores an
    incomplete trailing sequence to be prefixed to the next PTY chunk.
    """
    if not text and not carry:
        return '', ''
    src = (carry or '') + (text or '')
    out: list[str] = []
    i = 0
    n = len(src)

    while i < n:
        i, carry_out, clean_char = _consume_sanitizer_step(src, i)
        if carry_out is not None:
            return ''.join(out), carry_out
        if clean_char is not None:
            out.append(clean_char)

    return _finalize_sanitized_chunk(src, out)


@dataclass
class InteractiveSessionConfig:
    """Startup configuration for an interactive PTY session."""

    argv: Sequence[str] | str
    cwd: str | None = None
    env: Mapping[str, str] | None = None
    dimensions: tuple[int, int] = DEFAULT_DIMENSIONS
    encoding: str = 'utf-8'
    encoding_errors: str = 'replace'
    buffer_chars: int = DEFAULT_BUFFER_CHARS
    read_chunk_bytes: int = DEFAULT_READ_CHUNK
    extra_spawn_kwargs: dict[str, Any] = field(default_factory=dict)

    def normalized_argv(self) -> list[str]:
        """Return argv as a list of strings regardless of input shape."""
        if isinstance(self.argv, str):
            if IS_WINDOWS:
                return [self.argv]
            return shlex.split(self.argv)
        argv_list = [str(token) for token in self.argv]
        if not argv_list:
            raise InteractiveSessionError('argv must not be empty')
        return argv_list


def _spawn_backend(config: InteractiveSessionConfig) -> Any:
    """Spawn the platform-specific PTY process and return the backend handle.

    The returned object exposes the subset of attributes / methods we use:
    ``read``, ``write``, ``setwinsize``, ``isalive``, ``terminate``, ``kill``
    (POSIX only), ``wait``, ``pid``, and ``exitstatus``.
    """
    rows, cols = config.dimensions
    argv = config.normalized_argv()
    env = dict(config.env) if config.env is not None else None
    cwd = config.cwd

    if IS_WINDOWS:
        try:
            from winpty import PtyProcess  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - import guard
            raise PtyUnavailableError(
                'pywinpty is required for interactive terminals on Windows. '
                "Install it with: `pip install 'pywinpty>=2.0'`."
            ) from exc

        # pywinpty accepts either a list or a pre-formatted command line.
        # Passing the list through preserves argument boundaries; building
        # a string via ``subprocess.list2cmdline`` introduces quotes that
        # ``cmd.exe`` does not re-parse correctly for ``/c`` / ``/k``.
        spawn_arg: Sequence[str] | str
        if isinstance(config.argv, str):
            spawn_arg = config.argv
        else:
            spawn_arg = argv
        return PtyProcess.spawn(
            spawn_arg,
            cwd=cwd,
            env=env,
            dimensions=(rows, cols),
            **config.extra_spawn_kwargs,
        )

    try:
        from ptyprocess import PtyProcessUnicode  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - import guard
        raise PtyUnavailableError(
            'ptyprocess is required for interactive terminals on POSIX. '
            "Install it with: `pip install 'ptyprocess>=0.7'`."
        ) from exc

    return PtyProcessUnicode.spawn(
        argv,
        cwd=cwd,
        env=env,
        dimensions=(rows, cols),
        **config.extra_spawn_kwargs,
    )


class InteractiveSession:
    """OS-agnostic interactive PTY-backed session.

    Lifecycle:
        session = InteractiveSession(config)
        session.start()
        session.send_line('echo hello')
        output = session.read(timeout=1.0)
        session.close()

    Threading model:
        A daemon reader thread calls ``backend.read(chunk)`` in a loop and
        appends decoded text to an internal buffer protected by a lock.
        Consumers call :meth:`read` / :meth:`read_since` to drain output.

    Buffer semantics:
        Output is stored in a bounded in-memory string buffer. When the
        buffer would exceed ``config.buffer_chars``, the oldest characters
        are dropped while ``produced_chars`` keeps advancing monotonically,
        so consumers can detect truncation by comparing to ``peek()``
        length.
    """

    def __init__(self, config: InteractiveSessionConfig) -> None:
        self._config = config
        self._backend: Any | None = None
        self._buffer: list[str] = []
        self._buffer_chars: int = 0
        self._produced_chars: int = 0
        self._dropped_chars: int = 0
        self._lock = threading.RLock()
        self._data_event = threading.Event()
        self._reader_thread: threading.Thread | None = None
        self._stop_reader = threading.Event()
        self._started = False
        self._closed = False
        self._exit_code: int | None = None
        self._eof = False
        self._sanitize_carry = ''

    @property
    def pid(self) -> int | None:
        """Return the PID of the child process, or None if not started."""
        if self._backend is None:
            return None
        return int(getattr(self._backend, 'pid', 0)) or None

    @property
    def produced_chars(self) -> int:
        """Total characters produced since start (monotonic; survives trims)."""
        with self._lock:
            return self._produced_chars

    @property
    def dropped_chars(self) -> int:
        """Characters dropped from the head of the buffer due to size cap."""
        with self._lock:
            return self._dropped_chars

    @property
    def is_started(self) -> bool:
        return self._started

    @property
    def is_closed(self) -> bool:
        return self._closed

    def is_alive(self) -> bool:
        """Return True if the child process is still running."""
        if self._backend is None or self._closed:
            return False
        try:
            return bool(self._backend.isalive())
        except Exception:
            return False

    @property
    def exit_code(self) -> int | None:
        """Return exit code if the process has exited, else None."""
        if self._exit_code is not None:
            return self._exit_code
        if self._backend is None:
            return None
        status = getattr(self._backend, 'exitstatus', None)
        if status is not None:
            self._exit_code = int(status)
        return self._exit_code

    def start(self) -> None:
        """Spawn the child process and begin draining output.

        Raises:
            InteractiveSessionError: if the session has already been started.
            PtyUnavailableError: if the platform PTY backend is missing.
        """
        if self._started:
            raise InteractiveSessionError('session already started')
        if self._closed:
            raise InteractiveSessionError('session is closed')

        self._backend = _spawn_backend(self._config)
        self._started = True
        self._reader_thread = threading.Thread(
            target=self._reader_loop,
            name=f'pty-reader-{self.pid or "pending"}',
            daemon=True,
        )
        self._reader_thread.start()
        logger.debug(
            'InteractiveSession started (pid=%s, argv=%s, cwd=%s)',
            self.pid,
            self._config.normalized_argv(),
            self._config.cwd,
        )

    def _read_backend_chunk(self, backend: Any, chunk_size: int) -> Any | None:
        try:
            return backend.read(chunk_size)
        except EOFError:
            self._eof = True
            return None
        except OSError as exc:
            if exc.errno in (errno.EIO, errno.EBADF):
                self._eof = True
                return None
            logger.warning('PTY reader OSError: %s', exc)
            return None
        except Exception as exc:
            if self._stop_reader.is_set() or self._closed:
                return None
            logger.warning('PTY reader unexpected error: %s', exc)
            return None

    def _handle_empty_reader_chunk(self) -> bool:
        if not self.is_alive():
            self._eof = True
            return False
        time.sleep(0.01)
        return True

    def _decode_reader_chunk(self, chunk: Any) -> str:
        if isinstance(chunk, bytes):
            return chunk.decode(
                self._config.encoding, errors=self._config.encoding_errors
            )
        return str(chunk)

    def _reader_loop(self) -> None:
        """Background reader: blocking reads from the PTY into the buffer."""
        backend = self._backend
        assert backend is not None
        chunk_size = self._config.read_chunk_bytes
        while not self._stop_reader.is_set():
            chunk = self._read_backend_chunk(backend, chunk_size)
            if chunk is None:
                break

            if not chunk:
                if not self._handle_empty_reader_chunk():
                    break
                continue

            self._append_to_buffer(self._decode_reader_chunk(chunk))

        self._data_event.set()

    def _append_to_buffer(self, text: str) -> None:
        if not text:
            return
        clean, next_carry = _sanitize_terminal_text_chunk(
            text,
            carry=self._sanitize_carry,
        )
        self._sanitize_carry = next_carry
        if not clean:
            return
        with self._lock:
            self._buffer.append(clean)
            self._buffer_chars += len(clean)
            self._produced_chars += len(clean)
            self._trim_locked()
        self._data_event.set()

    def _trim_locked(self) -> None:
        cap = self._config.buffer_chars
        if self._buffer_chars <= cap:
            return
        overflow = self._buffer_chars - cap
        dropped = 0
        while overflow > 0 and self._buffer:
            head = self._buffer[0]
            if len(head) <= overflow:
                self._buffer.pop(0)
                overflow -= len(head)
                dropped += len(head)
            else:
                self._buffer[0] = head[overflow:]
                dropped += overflow
                overflow = 0
        self._buffer_chars -= dropped
        self._dropped_chars += dropped

    def write(self, data: str) -> int:
        """Write raw characters to the PTY. Returns characters written."""
        self._require_active()
        if not data:
            return 0
        try:
            written = self._backend.write(data)  # type: ignore[union-attr]
        except Exception as exc:
            raise InteractiveSessionError(f'failed to write to session: {exc}') from exc
        if isinstance(written, int):
            return written
        return len(data)

    def send_line(self, line: str, *, newline: str | None = None) -> int:
        r"""Write a line followed by a newline sequence.

        Defaults to ``\r`` on Windows (bare CR is the ConPTY submit signal;
        trailing LF causes PowerShell to enter ``>>`` continuation mode) and
        ``\n`` on POSIX.  Pass an explicit ``newline`` to override.
        """
        if newline is None:
            newline = '\r' if IS_WINDOWS else '\n'
        return self.write(f'{line}{newline}')

    def send_control(self, key: str) -> int:
        """Send a named control sequence such as ``c``, ``d``, ``esc``.

        Raises:
            KeyError: if the alias is not recognized.
        """
        seq = CONTROL_SEQUENCES[key.lower()]
        return self.write(seq)

    def resize(self, rows: int, cols: int) -> None:
        """Resize the PTY window."""
        self._require_active()
        if rows <= 0 or cols <= 0:
            raise InteractiveSessionError('rows and cols must be positive')
        try:
            self._backend.setwinsize(rows, cols)  # type: ignore[union-attr]
        except Exception as exc:
            raise InteractiveSessionError(f'resize failed: {exc}') from exc

    def peek(self) -> str:
        """Return the current buffered output without consuming it."""
        with self._lock:
            return ''.join(self._buffer)

    def read(
        self,
        *,
        timeout: float = 0.0,
        consume: bool = True,
    ) -> str:
        """Return buffered output.

        Args:
            timeout: if >0, wait up to ``timeout`` seconds for new output
                when the buffer is currently empty. If 0, return immediately.
            consume: if True, clear the buffer after reading.
        """
        deadline = time.monotonic() + timeout if timeout > 0 else 0.0
        while True:
            with self._lock:
                has_data = bool(self._buffer)
                if has_data or timeout <= 0 or self._eof or self._closed:
                    text = ''.join(self._buffer)
                    if consume and text:
                        self._buffer.clear()
                        self._buffer_chars = 0
                    return text
                self._data_event.clear()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                continue
            self._data_event.wait(timeout=remaining)

    def read_since(self, offset: int) -> tuple[str, int]:
        """Return output produced after ``offset`` plus the new offset.

        The returned offset should be passed back on the next call. This is
        non-destructive: it does not drain the buffer. If ``offset`` is older
        than the retained window, only the still-available tail is returned.
        """
        with self._lock:
            current = self._produced_chars
            if offset >= current:
                return '', current
            buffer_text = ''.join(self._buffer)
            buffer_start = current - len(buffer_text)
            if offset >= buffer_start:
                return buffer_text[offset - buffer_start :], current
            return buffer_text, current

    def wait_for_output(
        self,
        *,
        predicate,
        timeout: float,
        poll_interval: float = 0.05,
    ) -> bool:
        """Block until ``predicate(peek())`` is truthy or ``timeout`` elapses.

        Does not consume the buffer. Returns True if the predicate matched.
        """
        deadline = time.monotonic() + timeout
        while True:
            if predicate(self.peek()):
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            self._data_event.clear()
            self._data_event.wait(timeout=min(poll_interval, remaining))

    def wait(self, timeout: float | None = None) -> int | None:
        """Wait for the child to exit. Returns exit code, or None on timeout.

        Once the exit code has been captured it is cached; subsequent calls
        return the same value without re-reading the backend (whose status
        fields may become volatile after an explicit terminate on some
        platforms).
        """
        if self._exit_code is not None:
            return self._exit_code
        if self._backend is None:
            return None
        deadline = None if timeout is None else time.monotonic() + timeout
        while self.is_alive():
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                time.sleep(min(0.05, remaining))
            else:
                time.sleep(0.05)
        status = getattr(self._backend, 'exitstatus', None)
        if status is not None:
            self._exit_code = int(status)
        return self._exit_code

    def terminate(self, *, grace_seconds: float = 1.0) -> int | None:
        """Politely terminate the child, escalating to force kill if needed.

        On POSIX this sends SIGHUP via ptyprocess and falls back to SIGKILL.
        On Windows, ConPTY terminates the console which propagates to the
        child process tree.
        """
        if self._backend is None or self._closed:
            return self._exit_code
        if not self.is_alive():
            if self._exit_code is None:
                status = getattr(self._backend, 'exitstatus', None)
                if status is not None:
                    self._exit_code = int(status)
            return self._exit_code
        try:
            self._backend.terminate(force=False)
        except Exception as exc:
            logger.debug('terminate(force=False) raised: %s', exc)

        if grace_seconds > 0:
            result = self.wait(timeout=grace_seconds)
            if result is not None:
                return result

        try:
            self._backend.terminate(force=True)
        except Exception as exc:
            logger.debug('terminate(force=True) raised: %s', exc)

        return self.wait(timeout=max(grace_seconds, 1.0))

    def close(self, *, grace_seconds: float = 1.0) -> int | None:
        """Terminate the child and shut down the reader thread."""
        if self._closed:
            return self._exit_code
        exit_code = self.terminate(grace_seconds=grace_seconds)
        self._stop_reader.set()
        self._data_event.set()
        if self._reader_thread is not None and self._reader_thread.is_alive():
            try:
                self._reader_thread.join(timeout=1.0)
            except KeyboardInterrupt:
                # Interpreter shutdown (e.g. Ctrl+C) can raise here on Windows; avoid
                # noisy "Exception ignored in atexit" while the process is exiting.
                logger.debug(
                    'reader thread join interrupted during close', exc_info=True
                )
        self._closed = True
        logger.debug(
            'InteractiveSession closed (pid=%s, exit=%s)',
            self.pid,
            exit_code,
        )
        return exit_code

    def __enter__(self) -> InteractiveSession:
        if not self._started:
            self.start()
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def _require_active(self) -> None:
        if not self._started:
            raise InteractiveSessionError('session not started')
        if self._closed:
            raise InteractiveSessionError('session is closed')
        if self._backend is None:
            raise InteractiveSessionError('session backend is missing')


def create_interactive_session(
    argv: Sequence[str] | str,
    *,
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
    dimensions: tuple[int, int] = DEFAULT_DIMENSIONS,
    encoding: str = 'utf-8',
    encoding_errors: str = 'replace',
    buffer_chars: int = DEFAULT_BUFFER_CHARS,
    start: bool = True,
    **extra_spawn_kwargs: Any,
) -> InteractiveSession:
    """Convenience factory: build a config, instantiate, optionally start."""
    config = InteractiveSessionConfig(
        argv=argv,
        cwd=cwd,
        env=env,
        dimensions=dimensions,
        encoding=encoding,
        encoding_errors=encoding_errors,
        buffer_chars=buffer_chars,
        extra_spawn_kwargs=dict(extra_spawn_kwargs),
    )
    session = InteractiveSession(config)
    if start:
        session.start()
    return session


__all__ = [
    'CONTROL_SEQUENCES',
    'DEFAULT_BUFFER_CHARS',
    'DEFAULT_DIMENSIONS',
    'DEFAULT_READ_CHUNK',
    'InteractiveSession',
    'InteractiveSessionConfig',
    'InteractiveSessionError',
    'PtyUnavailableError',
    '_sanitize_terminal_text_chunk',
    'create_interactive_session',
]
