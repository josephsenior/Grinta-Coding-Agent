"""Session manager for handling multiple shell sessions."""

from __future__ import annotations

import logging
import os
import uuid
from typing import TYPE_CHECKING, Dict, Optional

from backend.runtime.utils.process_registry import TaskCancellationService
from backend.runtime.utils.unified_shell import UnifiedShellSession, create_shell_session

if TYPE_CHECKING:
    from backend.runtime.tools import ToolRegistry  # type: ignore[import-not-found]

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages multiple shell sessions."""

    def __init__(
        self,
        work_dir: str,
        username: str,
        tool_registry: Optional[ToolRegistry] = None,
        max_memory_gb: Optional[int] = None,
        cancellation_service: Optional[TaskCancellationService] = None,
    ) -> None:
        """Initialize the session manager.

        Args:
            work_dir: The initial working directory.
            username: The username for sessions.
            tool_registry: Optional tool registry.
            max_memory_gb: Optional memory limit in GB.
            cancellation_service: Optional cancellation service.
        """
        self.work_dir = work_dir
        self.username = username
        self.tool_registry = tool_registry
        self.max_memory_gb = max_memory_gb
        self.cancellation_service = cancellation_service or TaskCancellationService(
            label=f"sessions:{work_dir}"
        )
        self.sessions: Dict[str, UnifiedShellSession] = {}
        self._ensure_tool_registry()

    def _ensure_tool_registry(self) -> None:
        """Ensure tool registry exists."""
        if self.tool_registry is None:
            try:
                from backend.runtime.tools import ToolRegistry

                self.tool_registry = ToolRegistry()
            except ImportError:
                # This should ideally not happen if properly installed
                logger.warning("Failed to import ToolRegistry")

    def create_session(
        self, session_id: Optional[str] = None, cwd: Optional[str] = None
    ) -> UnifiedShellSession:
        """Create and initialize a new shell session.

        Args:
            session_id: Optional ID for the session. If None, one will be generated.
            cwd: Optional working directory. Defaults to initial work_dir.

        Returns:
            The created UnifiedShellSession.
        """
        if not session_id:
            session_id = str(uuid.uuid4())

        logger.info("Creating session %s (cwd=%s)", session_id, cwd or self.work_dir)
        
        try:
            session = create_shell_session(
                work_dir=cwd or self.work_dir,
                tools=self.tool_registry,
                username=self.username,
                no_change_timeout_seconds=int(
                    os.environ.get("NO_CHANGE_TIMEOUT_SECONDS", 10)
                ),
                max_memory_mb=self.max_memory_gb * 1024 if self.max_memory_gb else None,
                cancellation_service=self.cancellation_service,
            )
            session.initialize()
            self.sessions[session_id] = session
            logger.info("Session %s initialized successfully", session_id)
            return session
        except Exception as e:
            logger.error("Failed to create session %s: %s", session_id, e)
            raise

    def get_session(self, session_id: str) -> Optional[UnifiedShellSession]:
        """Retrieve an existing session by ID."""
        return self.sessions.get(session_id)

    def close_session(self, session_id: str) -> None:
        """Close and remove a specific session."""
        session = self.sessions.pop(session_id, None)
        if session:
            try:
                session.close()
            except Exception as e:
                logger.error("Error closing session %s: %s", session_id, e)

    def close_all(self) -> None:
        """Close all active sessions."""
        self.cancellation_service.cancel_all()
        for session_id, session in list(self.sessions.items()):
            try:
                session.close()
            except Exception:
                pass
        self.sessions.clear()

    @property
    def default_session(self) -> Optional[UnifiedShellSession]:
        """Get the default session if it exists."""
        return self.sessions.get("default")
