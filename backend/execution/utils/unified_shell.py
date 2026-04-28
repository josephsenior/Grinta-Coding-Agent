"""Unified shell session abstraction for cross-platform runtime.

Provides a consistent interface for shell operations across different platforms
and shell types (Bash, PowerShell, etc.).
"""

from __future__ import annotations

import os
import re
import sys
import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Protocol, cast

from backend.core.logger import app_logger as logger
from backend.core.os_capabilities import OS_CAPS
from backend.execution.sandboxing import (
    is_sandboxed_local_profile,
    resolve_execution_sandbox_policy,
)
from backend.execution.utils.tool_registry import resolve_windows_powershell_preference

if TYPE_CHECKING:
    from backend.execution.utils.process_registry import TaskCancellationService
    from backend.execution.utils.server_detector import DetectedServer
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
        security_config: object | None = None,
        workspace_root: str | None = None,
    ) -> None:
        """Initialize base shell session.

        Args:
            work_dir: Working directory for the session
            username: Optional username
            no_change_timeout_seconds: Timeout for no output change
            max_memory_mb: Optional memory limit
            cancellation_service: Service for handling task cancellation
            security_config: Optional execution security policy/configuration
            workspace_root: Optional workspace root used for boundary checks
        """
        self._closed = False
        self._initialized = False
        self.work_dir = os.path.abspath(work_dir)
        self.workspace_root = os.path.abspath(workspace_root or work_dir)
        self.username = username
        self._cwd: str = self.work_dir
        self.NO_CHANGE_TIMEOUT_SECONDS = no_change_timeout_seconds
        self.max_memory_mb = max_memory_mb
        self.security_config = security_config
        self._pending_bg_id: str | None = None
        self._bg_session_id: str | None = None
        self._detached_pane: Any | None = None
        self._detached_window: Any | None = None
        self._bg_process: Any | None = None
        self._bg_stdout_capture: Any | None = None
        self._bg_stderr_capture: Any | None = None
        from backend.execution.utils.process_registry import TaskCancellationService

        self._cancellation = cancellation_service or TaskCancellationService(
            label='runtime'
        )
        self._sandbox_policy = resolve_execution_sandbox_policy(
            security_config=security_config,
            workspace_root=self.workspace_root,
        )
        # T-P1-2: rolling buffer of the last command's combined stdout+stderr
        # so subprocess-backed sessions (SimpleBash / WindowsPowerShell) can
        # implement read_output() instead of returning ''.
        self._last_output_buffer: str = ''
        # T-P1-1: liveness timestamp for idle-session cleanup.
        self._last_interaction_at: float = time.time()

    def _wrap_subprocess_argv(self, argv: list[str], *, cwd: str) -> list[str]:
        """Prefix child argv with the active sandbox launcher when configured."""
        if self._sandbox_policy is None:
            return argv
        return self._sandbox_policy.wrap_argv(argv, cwd=cwd)

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

    def get_detected_server(self) -> DetectedServer | None:
        """Get and clear the last detected server.

        Default implementation returns None. Subclasses should override if
        they support server detection.
        """
        return None

    def read_output(self) -> str:
        """Read pending output from the shell session.

        Default implementation returns the rolling per-session buffer
        populated by ``_record_command_output``.  Subclasses with live
        interactive streams (e.g. tmux/PTY) should override.
        """
        return self._last_output_buffer

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

    def _run_backgroundable(
        self,
        process: Any,
        timeout: int | None,
        bg_id: str,
        *,
        is_text: bool = False,
    ) -> tuple[str, str, int]:
        """Monitor process with idle-output detection; detach to background on timeout.

        Provides the same "background + poll" semantics as ``BashSession``'s
        tmux-pane detach, but for subprocess-backed sessions
        (``SimpleBashSession``, ``WindowsPowershellSession``).

        Unlike ``bounded_communicate``, this does **not** kill the process on
        timeout.  Instead, it stores the process + ``OutputCapture`` objects as
        instance state so the caller can wrap them in a
        ``SubprocessBackgroundSession`` and register it with the session manager.

        Returns:
            ``(stdout, stderr, exit_code)`` — exit_code ``-2`` signals that the
            process was detached to a background session.  In that case,
            ``self._bg_process``, ``self._bg_session_id``,
            ``self._bg_stdout_capture``, and ``self._bg_stderr_capture`` are
            populated for the caller to consume.
        """
        from backend.execution.utils.subprocess_background import OutputCapture

        stdout_cap = OutputCapture(process.stdout, is_text=is_text)
        stderr_cap = (
            OutputCapture(process.stderr, is_text=is_text) if process.stderr else None
        )

        hard_limit = float(timeout or 600)
        idle_timeout = float(self.NO_CHANGE_TIMEOUT_SECONDS)
        # T-P0-1: Slow-start commands (npm install, pip install, cargo build…)
        # often spend a long time fetching metadata before printing anything.
        # Give them an extra grace window for the FIRST output only; once any
        # output is observed, the normal idle threshold takes over.
        initial_grace = idle_timeout * 2

        wall_start = time.monotonic()
        last_change_time = time.monotonic()
        last_output_len = 0
        first_output_seen = False

        while True:
            if process.poll() is not None:
                # Command completed — drain remaining output.
                stdout_cap._thread.join(timeout=2.0)
                if stderr_cap:
                    stderr_cap._thread.join(timeout=2.0)
                return (
                    stdout_cap.read_all(),
                    stderr_cap.read_all() if stderr_cap else '',
                    process.returncode,
                )

            now = time.monotonic()

            current_len = len(stdout_cap.read_all()) + (
                len(stderr_cap.read_all()) if stderr_cap else 0
            )
            if current_len > last_output_len:
                last_output_len = current_len
                last_change_time = now
                first_output_seen = True

            effective_idle = idle_timeout if first_output_seen else initial_grace
            if now - last_change_time >= effective_idle:
                # Idle-output timeout — keep the process alive and detach it.
                logger.info(
                    'Subprocess idle-output timeout after %ss; detaching to bg session %s',
                    self.NO_CHANGE_TIMEOUT_SECONDS,
                    bg_id,
                )
                self._bg_process = process
                self._bg_session_id = bg_id
                self._bg_stdout_capture = stdout_cap
                self._bg_stderr_capture = stderr_cap
                partial = stdout_cap.read_all()
                err_partial = stderr_cap.read_all() if stderr_cap else ''
                combined = partial + (
                    f'\n[stderr so far]:\n{err_partial}' if err_partial else ''
                )
                return combined, '', -2

            if now - wall_start >= hard_limit:
                # Hard wall-clock safety-net — kill (same as original behaviour).
                logger.warning(
                    'Hard timeout after %ss; killing subprocess', hard_limit
                )
                try:
                    process.kill()
                except Exception:
                    pass
                # T-P1-3: drain capture threads so partial output isn't lost.
                try:
                    process.wait(timeout=2)
                except Exception:
                    pass
                stdout_cap._thread.join(timeout=2.0)
                if stderr_cap:
                    stderr_cap._thread.join(timeout=2.0)
                partial_out = stdout_cap.read_all()
                partial_err = stderr_cap.read_all() if stderr_cap else ''
                err_msg = (
                    f'Command exceeded hard timeout of {int(hard_limit)}s\n'
                    + (partial_err or '')
                )
                return partial_out, err_msg, 124

            time.sleep(0.5)

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

        # T-P1-2: capture output into the rolling buffer so that
        # ``read_output()`` and ``terminal_read(session_id="default")`` work
        # for non-tmux shells too.
        self._record_command_output(stdout, stderr)

        return format_shell_output(
            command=command,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            working_dir=self._cwd,
        )

    # ------------------------------------------------------------------
    # Output buffer helpers (T-P1-2)
    # ------------------------------------------------------------------
    _MAX_OUTPUT_BUFFER_BYTES = 16 * 1024 * 1024  # 16 MiB

    def _record_command_output(self, stdout: str, stderr: str) -> None:
        """Update the rolling buffer with the most recent command output.

        Replaces (rather than appends) so ``read_output()`` always returns the
        most recently completed command's full output.  Bounded at 16 MiB to
        mirror ``OutputCapture``'s cap; oversize chunks are truncated from the
        head with a single marker.
        """
        combined = stdout or ''
        if stderr:
            combined = (
                combined + '\n[stderr]:\n' + stderr if combined else stderr
            )
        if len(combined) > self._MAX_OUTPUT_BUFFER_BYTES:
            keep = self._MAX_OUTPUT_BUFFER_BYTES
            combined = (
                '\n[... earlier output truncated ...]\n' + combined[-keep:]
            )
        self._last_output_buffer = combined
        self._last_interaction_at = time.time()

    # ------------------------------------------------------------------
    # CWD-changing command detection (T-P0-3)
    # ------------------------------------------------------------------
    # Matches `cd`, `pushd`, `popd`, `chdir` only when they appear as a
    # statement-leading token (start of string, or after a shell separator).
    _CD_TOKEN_RE = re.compile(r'(?:^|[;&|\n]|&&|\|\|)\s*(?:cd|pushd|popd|chdir)\b')
    # PowerShell variant — also covers `sl` and `Set-Location` aliases.
    _PS_CD_TOKEN_RE = re.compile(
        r'(?:^|[;|\n]|&&|\|\|)\s*(?:cd|sl|chdir|pushd|popd|Set-Location)\b',
        re.IGNORECASE,
    )

    def _command_changes_cwd(self, command: str, *, powershell: bool = False) -> bool:
        """Return True if ``command`` invokes a CWD-changing builtin/alias.

        Replaces brittle substring checks (``'cd ' in command``) that
        produced false positives on ``cd_helper``, ``echo "cd /tmp"``,
        function definitions, etc.  The check operates on the raw command
        string and is OS-agnostic — callers select the dialect via
        ``powershell``.
        """
        if not command:
            return False
        pattern = self._PS_CD_TOKEN_RE if powershell else self._CD_TOKEN_RE
        return bool(pattern.search(command))

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
    security_config: object | None = None,
    workspace_root: str | None = None,
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
        security_config: Optional execution security policy/configuration
        workspace_root: Optional workspace root used for boundary checks
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
        'security_config': security_config,
        'workspace_root': workspace_root or work_dir,
    }

    sandboxed_local = is_sandboxed_local_profile(security_config)

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
    if OS_CAPS.is_windows:
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

    # Non-interactive sandboxed_local sessions must avoid tmux because command
    # isolation is applied by wrapping each subprocess. Interactive sessions are
    # intentionally unsandboxed, so tmux remains a valid fallback when the PTY
    # backend is unavailable.
    if resolved_tools.has_tmux and resolved_tools.has_bash and (
        interactive or not sandboxed_local
    ):
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
