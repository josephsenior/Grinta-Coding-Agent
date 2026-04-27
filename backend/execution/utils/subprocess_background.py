"""Background subprocess session for non-tmux environments.

Used when ``SimpleBashSession`` or ``WindowsPowershellSession`` idle-output
timeout fires: the process is kept alive, its output captured via background
threads, and the agent can poll via ``terminal_read(session_id=<bg_id>)``.

This provides the same "background + poll" semantics that ``BashSession``
achieves via tmux pane detach, making the behaviour OS-agnostic across all
three session backends.
"""

from __future__ import annotations

import threading
from typing import IO, Any

# Maximum bytes retained per OutputCapture before older output is dropped.
# Keeps long-running background commands from exhausting RAM while still
# preserving recent context for `terminal_read`.
_MAX_BUFFER_BYTES = 16 * 1024 * 1024  # 16 MiB
_TRUNCATION_MARKER = '\n[... earlier output truncated ...]\n'


class OutputCapture:
    """Continuously drains a stream into a bounded buffer on a background thread.

    Works with both binary-mode (``bytes``) and text-mode (``str``) pipes so
    it can be paired with ``SimpleBashSession`` (binary) or
    ``WindowsPowershellSession`` (text).

    The internal buffer is capped at ``_MAX_BUFFER_BYTES``; when the cap is
    exceeded, oldest chunks are dropped and a single truncation marker is
    inserted at the head so the consumer knows data was lost.
    """

    def __init__(self, stream: IO[Any], *, is_text: bool = False) -> None:
        self._buf: list[str] = []
        self._buf_bytes: int = 0
        self._truncated: bool = False
        self._lock = threading.Lock()
        self._stream = stream
        self._is_text = is_text
        self._thread = threading.Thread(
            target=self._run, daemon=True, name='bg-output-capture'
        )
        self._thread.start()

    def _append(self, text: str) -> None:
        if not text:
            return
        with self._lock:
            self._buf.append(text)
            self._buf_bytes += len(text)
            # Roll oldest chunks off until we are back under the cap.
            while self._buf_bytes > _MAX_BUFFER_BYTES and len(self._buf) > 1:
                dropped = self._buf.pop(0)
                self._buf_bytes -= len(dropped)
                self._truncated = True

    def _run(self) -> None:
        try:
            if self._is_text:
                for line in iter(self._stream.readline, ''):
                    self._append(line)
            else:
                for chunk in iter(lambda: self._stream.read(4096), b''):
                    text = (
                        chunk.decode('utf-8', errors='replace')
                        if isinstance(chunk, bytes)
                        else chunk
                    )
                    self._append(text)
        except (OSError, ValueError):
            pass

    def read_all(self) -> str:
        with self._lock:
            body = ''.join(self._buf)
            if self._truncated:
                return _TRUNCATION_MARKER + body
            return body


class SubprocessBackgroundSession:
    """Read-only polling session wrapping a still-running subprocess.

    Created when a foreground command's idle-output timeout fires in
    ``SimpleBashSession`` or ``WindowsPowershellSession``.  The agent can
    call ``terminal_read(session_id=<bg_id>)`` to check for new output while
    the process continues running.

    Implements the same interface that ``terminal_read`` / ``_read_terminal_with_mode``
    expects from any shell session.
    """

    def __init__(
        self,
        process: Any,  # subprocess.Popen
        stdout_capture: OutputCapture,
        stderr_capture: OutputCapture | None,
        cwd: str,
    ) -> None:
        import time as _time

        self._process = process
        self._stdout_capture = stdout_capture
        self._stderr_capture = stderr_capture
        self._cwd = cwd
        # Liveness timestamp consulted by SessionManager.cleanup_idle_sessions.
        self._last_interaction_at: float = _time.time()

    # --- UnifiedShellSession-compatible interface ---

    def initialize(self) -> None:  # noqa: D401
        pass

    def execute(self, action: Any) -> Any:
        from backend.ledger.observation import ErrorObservation

        return ErrorObservation(
            'Cannot execute new commands on a background subprocess session.'
        )

    def close(self) -> None:
        try:
            if self._process.poll() is None:
                self._process.terminate()
                self._process.wait(timeout=5)
        except Exception:
            pass

    @property
    def cwd(self) -> str:
        return self._cwd

    def get_detected_server(self) -> None:
        return None

    def read_output(self) -> str:
        """Return the full captured output so far (stdout + optional stderr)."""
        import time as _time

        self._last_interaction_at = _time.time()
        out = self._stdout_capture.read_all()
        err = self._stderr_capture.read_all() if self._stderr_capture else ''
        if err:
            return out + '\n[stderr]:\n' + err
        return out

    def read_output_since(self, offset: int) -> tuple[str, int, None]:
        """Return (delta, next_offset, dropped_chars) for incremental reads."""
        full = self.read_output()
        total = len(full)
        safe = max(0, offset)
        return full[safe:], total, None

    def write_input(self, data: str, is_control: bool = False) -> None:
        """Forward input to the still-running process's stdin."""
        try:
            stdin = self._process.stdin
            if stdin is None:
                return
            payload: Any = data
            # Handle both text-mode and binary-mode stdin
            if hasattr(stdin, 'mode') and 'b' in getattr(stdin, 'mode', ''):
                payload = data.encode('utf-8') if isinstance(data, str) else data
            stdin.write(payload)
            stdin.flush()
        except Exception:
            pass
