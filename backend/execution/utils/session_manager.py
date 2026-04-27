"""Session manager for handling multiple shell sessions."""

from __future__ import annotations

import logging
import os
import uuid
from typing import TYPE_CHECKING, Optional, cast

from backend.execution.utils.process_registry import TaskCancellationService
from backend.execution.utils.unified_shell import (
    UnifiedShellSession,
    create_shell_session,
)

if TYPE_CHECKING:
    from backend.execution.utils.unified_shell import ShellToolRegistryLike

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages multiple shell sessions."""

    def __init__(
        self,
        work_dir: str,
        username: str,
        tool_registry: Optional[ShellToolRegistryLike] = None,
        max_memory_gb: Optional[int] = None,
        cancellation_service: Optional[TaskCancellationService] = None,
        security_config: object | None = None,
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
        self.security_config = security_config
        self.cancellation_service = cancellation_service or TaskCancellationService(
            label=f'sessions:{work_dir}'
        )
        self.sessions: dict[str, UnifiedShellSession] = {}
        self._ensure_tool_registry()

    def _ensure_tool_registry(self) -> None:
        """Ensure tool registry exists."""
        if self.tool_registry is None:
            try:
                from backend.execution.utils.tool_registry import ToolRegistry

                self.tool_registry = cast('ShellToolRegistryLike', ToolRegistry())
            except ImportError:
                # This should ideally not happen if properly installed
                logger.warning('Failed to import ToolRegistry')

    def create_session(
        self,
        session_id: Optional[str] = None,
        cwd: Optional[str] = None,
        *,
        interactive: bool = False,
    ) -> UnifiedShellSession:
        """Create and initialize a new shell session.

        Args:
            session_id: Optional ID for the session. If None, one will be generated.
            cwd: Optional working directory. Defaults to initial work_dir.
            interactive: If True, allocate a PTY-backed session supporting
                real-time ``read_output`` / ``write_input`` cross-platform.

        Returns:
            The created UnifiedShellSession.
        """
        if not session_id:
            session_id = str(uuid.uuid4())

        logger.info(
            'Creating session %s (cwd=%s, interactive=%s)',
            session_id,
            cwd or self.work_dir,
            interactive,
        )

        try:
            session = create_shell_session(
                work_dir=cwd or self.work_dir,
                tools=self.tool_registry,
                username=self.username,
                no_change_timeout_seconds=int(
                    os.environ.get('NO_CHANGE_TIMEOUT_SECONDS', 10)
                ),
                max_memory_mb=self.max_memory_gb * 1024 if self.max_memory_gb else None,
                cancellation_service=self.cancellation_service,
                interactive=interactive,
                security_config=self.security_config,
                workspace_root=self.work_dir,
            )
            session.initialize()
            self.sessions[session_id] = session
            logger.info('Session %s initialized successfully', session_id)
            return session
        except Exception as e:
            logger.error('Failed to create session %s: %s', session_id, e)
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
                logger.error('Error closing session %s: %s', session_id, e)

    def close_all(self) -> None:
        """Close all active sessions."""
        self.cancellation_service.cancel_all()
        for _session_id, session in list(self.sessions.items()):
            try:
                session.close()
            except Exception:
                pass
        self.sessions.clear()

    @property
    def default_session(self) -> Optional[UnifiedShellSession]:
        """Get the default session if it exists."""
        return self.sessions.get('default')

    def cleanup_idle_sessions(
        self,
        max_idle_seconds: int = 3600,
        *,
        require_exited: bool = True,
    ) -> list[str]:
        """Close background sessions whose underlying process exited and have
        been idle longer than ``max_idle_seconds``.

        T-P1-1: prevents unbounded growth of ``bg-XXXXXXXX`` background
        sessions and detached tmux windows over long autonomous runs.

        Parameters
        ----------
        max_idle_seconds : int
            Minimum idle time (seconds) before a candidate is eligible.
        require_exited : bool
            When True (default), only sessions whose backing process has
            exited are closed; still-running ones are kept regardless of
            idle time.  Set False to force-close idle background sessions
            even if the underlying process is alive (caller responsibility).

        Returns
        -------
        list[str]
            Session IDs that were closed.
        """
        import time as _time

        now = _time.time()
        closed: list[str] = []
        # Never auto-close the default foreground session.
        for sid in list(self.sessions.keys()):
            if sid == 'default':
                continue
            session = self.sessions.get(sid)
            if session is None:
                continue
            last_at = getattr(session, '_last_interaction_at', None)
            if last_at is None or (now - float(last_at)) < max_idle_seconds:
                continue
            if require_exited:
                proc = getattr(session, '_process', None)
                # SubprocessBackgroundSession exposes the live Popen as ``_process``.
                if proc is not None and getattr(proc, 'poll', lambda: None)() is None:
                    # process still running — skip
                    continue
            try:
                self.close_session(sid)
                closed.append(sid)
                logger.info(
                    'cleanup_idle_sessions: closed idle session %s', sid
                )
            except Exception:
                logger.warning(
                    'cleanup_idle_sessions: failed to close %s',
                    sid,
                    exc_info=True,
                )
        return closed
