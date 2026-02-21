"""Terminal manager for PTY-based interactive terminal sessions."""

import os
import time
import uuid
import libtmux
from libtmux.server import Server
from libtmux.session import Session

from backend.core.logger import forge_logger as logger
from backend.events.observation.error import ErrorObservation
from backend.events.observation.terminal import TerminalObservation
from backend.events.action.terminal import (
    TerminalRunAction,
    TerminalInputAction,
    TerminalReadAction,
)


class TerminalManager:
    """Manages true interactive PTY sessions using libtmux."""

    def __init__(self, work_dir: str, username: str | None = None) -> None:
        self.work_dir = work_dir
        self.username = username
        self.server: Server | None = None
        self.sessions: dict[str, Session] = {}

    def initialize(self) -> None:
        """Initialize the tmux server."""
        if self.server is None:
            self.server = libtmux.Server()

    def _require_server(self) -> Server:
        """Get the server or raise an error."""
        if not self.server:
            raise RuntimeError("TerminalManager server not initialized")
        return self.server

    def run(self, action: TerminalRunAction) -> TerminalObservation | ErrorObservation:
        """Start a new terminal session."""
        try:
            self.initialize()
            server = self._require_server()

            session_id = f"term-{uuid.uuid4().hex[:8]}"
            start_dir = action.cwd or self.work_dir
            command = action.command

            logger.info(
                f"Starting terminal session {session_id} with command: {command}"
            )

            session = server.new_session(
                session_name=session_id,
                start_directory=start_dir,
                kill_session=True,
                attach=False,
                window_name="terminal",
                window_command=command,
                x=1000,
                y=1000,
            )

            if session is None:
                return ErrorObservation(
                    f"Failed to create tmux session for {session_id}"
                )

            self.sessions[session_id] = session
            session.set_option("history-limit", "10000", _global=True)

            # Wait briefly for output to start
            time.sleep(0.5)

            return self.read(TerminalReadAction(session_id=session_id))

        except Exception as e:
            logger.error(f"Error starting terminal: {e}", exc_info=True)
            return ErrorObservation(f"Error starting terminal: {e}")

    def input(
        self, action: TerminalInputAction
    ) -> TerminalObservation | ErrorObservation:
        """Send input to an existing terminal session."""
        try:
            if action.session_id not in self.sessions:
                return ErrorObservation(
                    f"Terminal session {action.session_id} not found."
                )

            session = self.sessions[action.session_id]
            window = session.active_window
            if not window:
                return ErrorObservation(
                    f"No active window in session {action.session_id}"
                )

            pane = window.active_pane
            if not pane:
                return ErrorObservation(
                    f"No active pane in session {action.session_id}"
                )

            if action.is_control:
                # E.g., 'C-c' -> 'C-c'
                pane.send_keys(action.input, enter=False)
            else:
                pane.send_keys(action.input, enter=True)

            # Wait briefly for command to execute
            time.sleep(0.5)

            return self.read(TerminalReadAction(session_id=action.session_id))

        except Exception as e:
            logger.error(
                f"Error sending input to terminal {action.session_id}: {e}",
                exc_info=True,
            )
            return ErrorObservation(f"Error sending terminal input: {e}")

    def read(
        self, action: TerminalReadAction
    ) -> TerminalObservation | ErrorObservation:
        """Read the output buffer of an existing terminal session."""
        try:
            if action.session_id not in self.sessions:
                return ErrorObservation(
                    f"Terminal session {action.session_id} not found or finished."
                )

            session = self.sessions[action.session_id]
            window = session.active_window
            if not window:
                return ErrorObservation(
                    f"No active window in session {action.session_id}"
                )

            pane = window.active_pane
            if not pane:
                return ErrorObservation(
                    f"No active pane in session {action.session_id}"
                )

            content = "\n".join(
                line.rstrip()
                for line in pane.cmd("capture-pane", "-J", "-pS", "-").stdout
            )

            # If the pane has died, we might want to clean it up, but let's keep it until they explicitly close or we reap

            return TerminalObservation(session_id=action.session_id, content=content)

        except libtmux.exc.LibTmuxException as e:
            logger.warning(f"Terminal session {action.session_id} may have died: {e}")
            self.sessions.pop(action.session_id, None)
            return ErrorObservation(
                f"Terminal session {action.session_id} is no longer active."
            )
        except Exception as e:
            logger.error(
                f"Error reading terminal {action.session_id}: {e}", exc_info=True
            )
            return ErrorObservation(f"Error reading terminal: {e}")

    def close_all(self) -> None:
        """Close all terminal sessions."""
        for session_id, session in list(self.sessions.items()):
            try:
                session.kill()
            except Exception:
                pass
        self.sessions.clear()

    def close(self, session_id: str) -> None:
        """Close a specific terminal session."""
        if session_id in self.sessions:
            try:
                self.sessions[session_id].kill()
            except Exception:
                pass
            del self.sessions[session_id]
