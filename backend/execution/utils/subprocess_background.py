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


class OutputCapture:
    """Continuously drains a stream into a buffer on a background thread.

    Works with both binary-mode (``bytes``) and text-mode (``str``) pipes so
    it can be paired with ``SimpleBashSession`` (binary) or
    ``WindowsPowershellSession`` (text).
    """

    def __init__(self, stream: IO[Any], *, is_text: bool = False) -> None:
        self._buf: list[str] = []
        self._lock = threading.Lock()
        self._stream = stream
        self._is_text = is_text
        self._thread = threading.Thread(
            target=self._run, daemon=True, name='bg-output-capture'
        )
        self._thread.start()

    def _run(self) -> None:
        try:
            if self._is_text:
                for line in iter(self._stream.readline, ''):
                    with self._lock:
                        self._buf.append(line)
            else:
                for chunk in iter(lambda: self._stream.read(4096), b''):
                    text = (
                        chunk.decode('utf-8', errors='replace')
                        if isinstance(chunk, bytes)
                        else chunk
                    )
                    with self._lock:
                        self._buf.append(text)
        except (OSError, ValueError):
            pass

    def read_all(self) -> str:
        with self._lock:
            return ''.join(self._buf)


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
        self._process = process
        self._stdout_capture = stdout_capture
        self._stderr_capture = stderr_capture
        self._cwd = cwd

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
