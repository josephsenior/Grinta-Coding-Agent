"""Session Manager for handling active sessions."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from backend.core.logger import forge_logger as logger


@runtime_checkable
class Session(Protocol):
    """Lightweight protocol for session-like objects used by SessionManager.

    This avoids import-time coupling to the full Session implementation while
    preserving useful type information for tests and callers.
    """

    sid: str
    user_id: str | None


if TYPE_CHECKING:  # Prefer real type for static checkers when available
    pass


class SessionManager:
    """Manages active sessions in the application."""

    def __init__(self):
        """Initialize the active session registry."""
        self._active_sessions: dict[str, Session] = {}
        self._lock = threading.Lock()
        logger.info("SessionManager initialized")

    def get_active_sessions(self) -> dict[str, Session]:
        """Get all active sessions.

        Returns:
            Dictionary of active sessions keyed by session ID

        """
        with self._lock:
            return self._active_sessions.copy()

    def add_session(self, session: Session) -> None:
        """Add a session to the active sessions.

        Args:
            session: The session to add

        """
        with self._lock:
            self._active_sessions[session.sid] = session
        logger.info("Added session %s", session.sid)

    def remove_session(self, session_id: str) -> None:
        """Remove a session from active sessions.

        Args:
            session_id: The ID of the session to remove

        """
        with self._lock:
            removed = self._active_sessions.pop(session_id, None)
        if removed is not None:
            logger.info("Removed session %s", session_id)

    def get_session(self, session_id: str) -> Session | None:
        """Get a specific session by ID.

        Args:
            session_id: The ID of the session to retrieve

        Returns:
            The session if found, None otherwise

        """
        with self._lock:
            return self._active_sessions.get(session_id)

    def list_sessions(self) -> list[str]:
        """Return active session IDs (debug / diagnostics)."""
        with self._lock:
            return list(self._active_sessions.keys())

    def get_session_count(self) -> int:
        """Get the number of active sessions.

        Returns:
            Number of active sessions

        """
        with self._lock:
            return len(self._active_sessions)
