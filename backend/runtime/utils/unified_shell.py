"""Unified shell session abstraction for cross-platform runtime.

Provides a consistent interface for shell operations across different platforms
and shell types (Bash, PowerShell, etc.).
"""

from __future__ import annotations

import os
import sys
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from backend.core.logger import forge_logger as logger

if TYPE_CHECKING:
    from backend.events.action import CmdRunAction
    from backend.events.observation import Observation
    from backend.runtime.utils.process_registry import TaskCancellationService
    from backend.runtime.utils.tool_registry import ToolRegistry


class UnifiedShellSession(ABC):
    """Abstract base class for shell sessions.

    Provides a consistent interface regardless of the underlying shell
    implementation (Bash + tmux, PowerShell, simple subprocess, etc.).
    """

    @abstractmethod
    def initialize(self) -> None:
        """Initialize the shell session."""

    @abstractmethod
    def execute(self, action: CmdRunAction) -> Observation:
        """Execute a command in the shell."""

    @abstractmethod
    def close(self) -> None:
        """Close the shell session and clean up resources."""

    @property
    @abstractmethod
    def cwd(self) -> str:
        """Get current working directory."""

    @abstractmethod
    def get_detected_server(self):
        """Get and clear the last detected server."""

    @abstractmethod
    def read_output(self) -> str:
        """Read pending output from the shell session."""

    @abstractmethod
    def write_input(self, data: str, is_control: bool = False) -> None:
        """Write input to the shell session."""


class BaseShellSession(UnifiedShellSession, ABC):
    """Base class for shell sessions with common functionality.

    Handles initialization of common properties and provides utility methods.
    """

    def __init__(
        self,
        work_dir: str,
        username: str | None = None,
        no_change_timeout_seconds: int = 30,
        max_memory_mb: int | None = None,
        cancellation_service: TaskCancellationService | None = None,
    ) -> None:
        """Initialize base shell session.

        Args:
            work_dir: Working directory for the session
            username: Optional username
            no_change_timeout_seconds: Timeout for no output change
            max_memory_mb: Optional memory limit
            cancellation_service: Service for handling task cancellation
        """
        self._closed = False
        self._initialized = False
        self.work_dir = os.path.abspath(work_dir)
        self.username = username
        self._cwd: str = self.work_dir
        self.NO_CHANGE_TIMEOUT_SECONDS = no_change_timeout_seconds
        self.max_memory_mb = max_memory_mb
        from backend.runtime.utils.process_registry import TaskCancellationService

        self._cancellation = cancellation_service or TaskCancellationService(
            label="runtime"
        )

    @property
    def cwd(self) -> str:
        """Get current working directory."""
        return self._cwd

    def _normalize_timeout(self, timeout: int | str | None) -> int:
        """Normalize timeout value to an integer."""
        if timeout is None:
            return 60
        try:
            return int(timeout)
        except (TypeError, ValueError):
            return 60

    def _prepare_command(self, command: str) -> tuple[str, bool]:
        """Prepare command for execution, detecting background run.

        Args:
            command: Command string to prepare

        Returns:
            Tuple of (cleaned command, run_in_background flag)
        """
        command = command.strip()
        run_in_background = False
        if command.endswith("&"):
            run_in_background = True
            command = command[:-1].strip()
            logger.info("Detected background command: '%s'", command)
        return command, run_in_background

    def get_detected_server(self):
        """Get and clear the last detected server.

        Default implementation returns None. Subclasses should override if
        they support server detection.
        """
        return

    def read_output(self) -> str:
        """Read pending output from the shell session.

        Subclasses with interactive shell support should override this.
        """
        msg = f"{self.__class__.__name__} does not implement read_output()"
        raise NotImplementedError(msg)

    def write_input(self, data: str, is_control: bool = False) -> None:
        """Write input to the shell session.

        Subclasses with interactive shell support should override this.
        """
        msg = f"{self.__class__.__name__} does not implement write_input()"
        raise NotImplementedError(msg)

    def close(self) -> None:
        """Close the shell session and clean up resources."""
        self._closed = True
        logger.info("Shell session closed: %s", self.__class__.__name__)

    def _format_execution_observation(
        self, command: str, stdout: str, stderr: str, exit_code: int
    ) -> Observation:
        """Format the results of a command execution into an observation.

        Args:
            command: The command that was executed
            stdout: Standard output from the command
            stderr: Standard error from the command
            exit_code: Exit code from the command

        Returns:
            Observation with formatted output
        """
        from backend.runtime.utils.shell_utils import format_shell_output

        return format_shell_output(
            command=command,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            working_dir=self._cwd,
        )

    def _update_cwd_from_output(self, pwd_command: list[str]) -> None:
        """Update current working directory by running a PWD command.

        Args:
            pwd_command: Command to run to get current directory
        """
        import subprocess

        try:
            cwd_result = subprocess.run(
                pwd_command,
                cwd=self._cwd,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if cwd_result.returncode == 0:
                new_cwd = cwd_result.stdout.strip()
                if os.path.isdir(new_cwd):
                    self._cwd = new_cwd
        except Exception as e:
            logger.debug("Failed to update CWD: %s", e)


def create_shell_session(
    work_dir: str,
    tools: ToolRegistry | None = None,
    username: str | None = None,
    no_change_timeout_seconds: int = 30,
    max_memory_mb: int | None = None,
    cancellation_service: TaskCancellationService | None = None,
) -> UnifiedShellSession:
    """Factory function to create the appropriate shell session.

    Args:
        work_dir: Working directory for the session
        tools: ToolRegistry with detected tools (optional)
        username: Optional username for the session
        no_change_timeout_seconds: Timeout for no output change
        max_memory_mb: Optional memory limit

    Returns:
        Appropriate shell session implementation
    """
    if tools is None:
        from backend.runtime.utils.tool_registry import ToolRegistry

        tools = ToolRegistry()

    if cancellation_service is None:
        from backend.runtime.utils.process_registry import TaskCancellationService

        cancellation_service = TaskCancellationService(label="runtime")

    logger.info("Creating shell session for platform: %s", sys.platform)
    logger.info("Detected shell: %s", tools.shell_type)
    logger.info("Has tmux: %s", tools.has_tmux)

    # Common session arguments
    session_kwargs: dict[str, Any] = {
        "work_dir": work_dir,
        "username": username,
        "no_change_timeout_seconds": no_change_timeout_seconds,
        "max_memory_mb": max_memory_mb,
        "cancellation_service": cancellation_service,
    }

    # Windows: Prefer Git Bash (SimpleBashSession) when available.
    # LLMs generate bash commands natively; running them in bash eliminates
    # the need for fragile PowerShell translation regexes.
    if os.name == "nt":
        if tools.has_bash:
            from backend.runtime.utils.simple_bash import SimpleBashSession

            logger.info("Using SimpleBashSession (Git Bash on Windows)")
            return SimpleBashSession(**session_kwargs)

        # Fallback: no bash found — use PowerShell
        from backend.runtime.utils.windows_bash import WindowsPowershellSession

        logger.info("Using WindowsPowershellSession (no bash found)")
        return WindowsPowershellSession(
            **session_kwargs,  # type: ignore[arg-type]
            powershell_exe=tools.shell_type if tools.has_powershell else None,
        )

    # Unix with tmux: Use full BashSession
    if tools.has_tmux and tools.has_bash:
        from backend.runtime.utils.bash import BashSession

        logger.info("Using BashSession with tmux")
        return BashSession(**session_kwargs)

    # Unix without tmux: Use simple Bash session
    if tools.has_bash:
        from backend.runtime.utils.simple_bash import SimpleBashSession

        logger.info("Using SimpleBashSession (no tmux)")
        return SimpleBashSession(**session_kwargs)

    # Fallback: Should not happen if tools are detected correctly
    raise RuntimeError(
        f"No suitable shell found for platform {sys.platform}. Detected shell: {tools.shell_type}"
    )
