"""Unified shell session abstraction for cross-platform runtime.

Provides a consistent interface for shell operations across different platforms
and shell types (Bash, PowerShell, etc.).
"""

from __future__ import annotations

import os
import sys
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Protocol, cast

from backend.core.logger import app_logger as logger
from backend.execution.utils.tool_registry import resolve_windows_powershell_preference

if TYPE_CHECKING:
    from backend.execution.utils.process_registry import TaskCancellationService
    from backend.ledger.action import CmdRunAction
    from backend.ledger.observation import Observation


class ShellToolRegistryLike(Protocol):
    has_bash: bool
    has_powershell: bool
    has_tmux: bool
    shell_type: str
    is_container_runtime: bool
    is_wsl_runtime: bool


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
        from backend.execution.utils.process_registry import TaskCancellationService

        self._cancellation = cancellation_service or TaskCancellationService(
            label='runtime'
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
        if command.endswith('&'):
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
        msg = f'{self.__class__.__name__} does not implement read_output()'
        raise NotImplementedError(msg)

    def write_input(self, data: str, is_control: bool = False) -> None:
        """Write input to the shell session.

        Subclasses with interactive shell support should override this.
        """
        msg = f'{self.__class__.__name__} does not implement write_input()'
        raise NotImplementedError(msg)

    def resize(self, rows: int, cols: int) -> None:
        """Resize the interactive TTY (rows x columns).

        Subprocess-backed shells ignore this. PTY and tmux-backed sessions
        may override to update the emulated terminal dimensions.
        """

    def close(self) -> None:
        """Close the shell session and clean up resources."""
        self._closed = True
        logger.info('Shell session closed: %s', self.__class__.__name__)

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
        from backend.execution.utils.shell_utils import format_shell_output

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
            logger.debug('Failed to update CWD: %s', e)


def create_shell_session(
    work_dir: str,
    tools: ShellToolRegistryLike | None = None,
    username: str | None = None,
    no_change_timeout_seconds: int = 30,
    max_memory_mb: int | None = None,
    cancellation_service: TaskCancellationService | None = None,
    *,
    interactive: bool = False,
) -> UnifiedShellSession:
    """Factory function to create the appropriate shell session.

    Args:
        work_dir: Working directory for the session
        tools: ToolRegistry with detected tools (optional)
        username: Optional username for the session
        no_change_timeout_seconds: Timeout for no output change
        max_memory_mb: Optional memory limit
        cancellation_service: Optional hook to cancel in-flight shell work
        interactive: If True, return a PTY-backed session that supports
            real-time ``read_output`` / ``write_input`` cross-platform. Falls
            back to the legacy session if the PTY backend is unavailable.

    Returns:
        Appropriate shell session implementation
    """
    if tools is None:
        from backend.engine.tools.prompt import _get_global_tool_registry
        tools = cast(ShellToolRegistryLike, _get_global_tool_registry())

    resolved_tools = tools
    assert resolved_tools is not None

    if cancellation_service is None:
        from backend.execution.utils.process_registry import TaskCancellationService

        cancellation_service = TaskCancellationService(label='runtime')

    logger.info('Creating shell session for platform: %s', sys.platform)
    logger.info('Detected shell: %s', resolved_tools.shell_type)
    logger.info('Has tmux: %s', resolved_tools.has_tmux)
    logger.info(
        'Runtime context: container=%s wsl=%s',
        getattr(resolved_tools, 'is_container_runtime', False),
        getattr(resolved_tools, 'is_wsl_runtime', False),
    )

    # Common session arguments
    session_kwargs: dict[str, Any] = {
        'work_dir': work_dir,
        'username': username,
        'no_change_timeout_seconds': no_change_timeout_seconds,
        'max_memory_mb': max_memory_mb,
        'cancellation_service': cancellation_service,
    }

    if interactive:
        try:
            from backend.execution.utils.pty_session import PtyUnavailableError
            from backend.execution.utils.pty_shell_session import (
                PtyInteractiveShellSession,
            )

            logger.info('Using PtyInteractiveShellSession (OS-agnostic PTY)')
            return PtyInteractiveShellSession(**session_kwargs)
        except PtyUnavailableError as exc:
            logger.warning(
                'Interactive PTY backend unavailable (%s); falling back to '
                'default shell session. Interactive read_output / write_input '
                'may be limited.',
                exc,
            )
        except Exception as exc:
            logger.warning(
                'Failed to start interactive PTY shell (%s); falling back to '
                'default shell session.',
                exc,
            )

    # Windows: Prefer PowerShell by default for native compatibility.
    # Users can force bash with APP_WINDOWS_SHELL_PREFERENCE=bash.
    if os.name == 'nt':
        prefer_powershell = resolve_windows_powershell_preference(
            has_bash=resolved_tools.has_bash,
            has_powershell=resolved_tools.has_powershell,
        )

        if prefer_powershell and resolved_tools.has_powershell:
            from backend.execution.utils.windows_bash import WindowsPowershellSession

            logger.info(
                'Using WindowsPowershellSession (preferred on Windows). '
                'Set APP_WINDOWS_SHELL_PREFERENCE=bash to prefer Git Bash.'
            )
            return WindowsPowershellSession(
                **session_kwargs,  # type: ignore[arg-type]
                powershell_exe=(
                    resolved_tools.shell_type if resolved_tools.has_powershell else None
                ),
            )

        if resolved_tools.has_bash:
            from backend.execution.utils.simple_bash import SimpleBashSession

            logger.info(
                'Using SimpleBashSession (Git Bash on Windows). '
                'Set APP_WINDOWS_SHELL_PREFERENCE=powershell to prefer PowerShell.'
            )
            return SimpleBashSession(**session_kwargs)

        # Fallback: no bash found — use PowerShell
        from backend.execution.utils.windows_bash import WindowsPowershellSession

        logger.warning(
            'Bash unavailable on Windows; falling back to PowerShell session. '
            'For full Linux runtime behavior (tmux/interactivity), use Docker or WSL.'
        )
        return WindowsPowershellSession(
            **session_kwargs,  # type: ignore[arg-type]
            powershell_exe=(
                resolved_tools.shell_type if resolved_tools.has_powershell else None
            ),
        )

    # Unix with tmux: Use full BashSession
    if resolved_tools.has_tmux and resolved_tools.has_bash:
        from backend.execution.utils.bash import BashSession

        logger.info('Using BashSession with tmux')
        return BashSession(**session_kwargs)

    # Unix without tmux: Use simple Bash session
    if resolved_tools.has_bash:
        from backend.execution.utils.simple_bash import SimpleBashSession

        logger.info('Using SimpleBashSession (no tmux)')
        return SimpleBashSession(**session_kwargs)

    # Fallback: Should not happen if tools are detected correctly
    raise RuntimeError(
        f'No suitable shell found for platform {sys.platform}. Detected shell: {resolved_tools.shell_type}'
    )
