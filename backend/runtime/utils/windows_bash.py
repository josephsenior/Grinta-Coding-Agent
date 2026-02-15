"""This module provides a Windows-specific implementation for running commands in PowerShell.

Uses subprocess calls to pwsh.exe (PowerShell 7) or powershell.exe (Windows PowerShell).
This is simpler and more reliable than using the .NET SDK via pythonnet.
"""

from __future__ import annotations

import sys

# CRITICAL: Platform check MUST be the very first thing after imports
if sys.platform != "win32":

    class WindowsOnlyModuleError(RuntimeError):
        """Raised when Windows-specific module functionality is accessed on unsupported platforms."""

        def __init__(self, module: str):
            super().__init__(
                f"FATAL ERROR: This module ({module}) requires Windows platform, "
                f"but is running on {sys.platform}. This should never happen and indicates a "
                f"serious configuration issue. Please use the appropriate platform-specific runtime."
            )

    raise WindowsOnlyModuleError("windows_bash.py")

import os
import subprocess
from threading import RLock
from typing import TYPE_CHECKING

from backend.core.logger import FORGE_logger as logger
from backend.events.observation import ErrorObservation
from backend.events.observation.commands import (
    CmdOutputMetadata,
    CmdOutputObservation,
)
from backend.runtime.utils.process_registry import TaskCancellationService

if TYPE_CHECKING:
    from backend.events.action import CmdRunAction


def _find_powershell_executable() -> str:
    """Find the best available PowerShell executable.

    Returns:
        Path to pwsh.exe (PowerShell 7) or powershell.exe (Windows PowerShell)

    Raises:
        RuntimeError: If no PowerShell executable is found
    """
    # Try PowerShell 7 first (pwsh.exe)
    try:
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-Command", "$PSVersionTable.PSVersion"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            logger.info("Found PowerShell 7 (pwsh.exe)")
            return "pwsh"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Fall back to Windows PowerShell
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "$PSVersionTable.PSVersion"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            logger.info("Found Windows PowerShell (powershell.exe)")
            return "powershell"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    raise RuntimeError(
        "PowerShell is required on Windows but could not be found. "
        "Please install PowerShell 7 (https://aka.ms/powershell) or ensure Windows PowerShell is available."
    )


from backend.runtime.utils.unified_shell import BaseShellSession  # noqa: E402


class WindowsPowershellSession(BaseShellSession):
    """Manages PowerShell command execution using subprocess calls.

    Executes commands via pwsh.exe or powershell.exe, maintaining working directory
    state between calls. Simpler and more reliable than .NET SDK approach.
    """

    def __init__(
        self,
        work_dir: str,
        username: str | None = None,
        no_change_timeout_seconds: int = 30,
        max_memory_mb: int | None = None,
        cancellation_service: TaskCancellationService | None = None,
        powershell_exe: str | None = None,
    ) -> None:
        """Initializes the PowerShell session."""
        super().__init__(
            work_dir=work_dir,
            username=username,
            no_change_timeout_seconds=no_change_timeout_seconds,
            max_memory_mb=max_memory_mb,
            cancellation_service=cancellation_service,
        )
        self._job_lock = RLock()

        try:
            self.powershell_exe = powershell_exe or _find_powershell_executable()
            # Verify the working directory exists
            if not os.path.isdir(self._cwd):
                os.makedirs(self._cwd, exist_ok=True)
                logger.info("Created working directory: %s", self._cwd)
            self._initialized = True
            logger.info(
                "PowerShell session initialized. Using: %s, Initial CWD: %s",
                self.powershell_exe,
                self._cwd,
            )
        except Exception as e:
            logger.error("Failed to initialize PowerShell session: %s", e)
            self.close()
            raise RuntimeError(f"Failed to initialize PowerShell session: {e}") from e

    def initialize(self) -> None:
        """Initialize the session (already done in __init__).

        This method is provided for compatibility with the base ShellSession interface.
        """
        if not self._initialized:
            raise RuntimeError("PowerShell session failed to initialize in __init__")

    def _run_command(
        self,
        command: str,
        timeout: int | None = None,
        cwd: str | None = None,
        input_text: str | None = None,
    ) -> tuple[str, str, int]:
        """Run a PowerShell command via subprocess.

        Args:
            command: The PowerShell command to execute.
            timeout: Timeout in seconds (None for no timeout).
            cwd: Working directory (None to use session CWD).
            input_text: Input to send to the command.

        Returns:
            Tuple of (stdout, stderr, exit_code)
        """
        if self._closed:
            raise RuntimeError("PowerShell session is closed")

        work_dir = cwd or self._cwd
        if not os.path.isdir(work_dir):
            work_dir = self.work_dir

        # Build PowerShell command
        # Use -NoProfile for faster startup, -Command to execute
        ps_command = [
            self.powershell_exe,
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            command,
        ]

        process = None
        try:
            # Use Popen instead of run to capture PID for cancellation service
            process = subprocess.Popen(
                ps_command,
                cwd=work_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE if input_text is not None else None,
                text=True,
            )

            # Register for cancellation
            self._cancellation.register_process(process)

            stdout, stderr = process.communicate(input=input_text, timeout=timeout)
            return_code = process.returncode

            # Update CWD if command changed directory
            if "cd " in command.lower() or "Set-Location" in command:
                self._update_cwd_from_output(  # type: ignore[attr-defined]
                    [
                        self.powershell_exe,
                        "-NoProfile",
                        "-Command",
                        "Get-Location | Select-Object -ExpandProperty Path",
                    ]
                )

            return (stdout, stderr, return_code)
        except subprocess.TimeoutExpired:
            return self._handle_timeout_exception(process, timeout, command)
        except Exception as e:
            return self._handle_run_exception(process, e)
        finally:
            if process:
                self._cancellation.unregister_process(process.pid)

    def execute(self, action: CmdRunAction) -> CmdOutputObservation | ErrorObservation:
        """Executes a command.

        Args:
            action: The command execution action.

        Returns:
            CmdOutputObservation or ErrorObservation.
        """
        if not self._session_ready():
            return self._session_not_ready_observation()

        command = action.command.strip()
        timeout_seconds_int = self._normalize_timeout(action.timeout)  # type: ignore[arg-type]
        is_input = action.is_input

        # Handle background commands (ending with &)
        command, run_in_background = self._prepare_command(command)

        logger.info(
            "Executing command: '%s', Timeout: %ss, is_input: %s, background: %s",
            command,
            timeout_seconds_int,
            is_input,
            run_in_background,
        )

        if run_in_background:
            return self._execute_background_command(command)

        # Regular foreground command
        return self._execute_foreground_command(
            command, timeout_seconds_int, action.stdin if is_input else None
        )

    def _update_cwd_if_needed(self) -> None:
        """Update current working directory by querying the shell."""
        self._update_cwd_from_output(
            [
                self.powershell_exe,
                "-NoProfile",
                "-Command",
                "Get-Location | Select-Object -ExpandProperty Path",
            ]
        )

    def _handle_timeout_exception(
        self, process: subprocess.Popen | None, timeout: int | None, command: str
    ) -> tuple[str, str, int]:
        """Handle subprocess timeout."""
        logger.warning("Command timed out after %s seconds: %s", timeout, command)
        if process:
            try:
                process.kill()
                process.wait()
            except Exception:
                pass
        return ("", f"Command timed out after {timeout} seconds", 124)

    def _handle_run_exception(
        self, process: subprocess.Popen | None, e: Exception
    ) -> tuple[str, str, int]:
        """Handle general subprocess exceptions."""
        logger.error("Error running PowerShell command: %s", e)
        if process:
            try:
                process.kill()
            except Exception:
                pass
        return ("", str(e), 1)

    def _execute_background_command(
        self, command: str
    ) -> CmdOutputObservation | ErrorObservation:
        """Start a background PowerShell process."""
        escaped_cwd = self._cwd.replace('"', '`"')
        child_script = f'Set-Location "{escaped_cwd}"; {command}'
        child_script_escaped = child_script.replace("'", "''")
        start_proc = (
            f"$p = Start-Process -FilePath '{self.powershell_exe}' -NoNewWindow -PassThru "
            f"-ArgumentList @('-NoProfile','-NonInteractive','-Command','{child_script_escaped}'); "
            "Write-Output $p.Id"
        )
        stdout, stderr, exit_code = self._run_command(start_proc, timeout=10)
        if exit_code == 0 and stdout.strip().isdigit():
            child_pid = int(stdout.strip())
            logger.info("Background process started with PID: %s", child_pid)
            self._cancellation.register_pid(child_pid)
            metadata = CmdOutputMetadata(
                exit_code=0,
                working_dir=self._cwd.replace("\\", "\\\\"),
            )
            return CmdOutputObservation(
                content=f"[{child_pid}]",
                command=command,
                metadata=metadata,
            )

        # Fallback: run normally if background start fails
        logger.warning("Failed to start background job, running normally")
        return self._execute_foreground_command(command, 60, None)

    def _execute_foreground_command(
        self, command: str, timeout: int, stdin: str | None
    ) -> CmdOutputObservation:
        """Execute a foreground command and format the observation."""
        stdout, stderr, exit_code = self._run_command(
            command,
            timeout=timeout,
            input_text=stdin,
        )

        return self._format_execution_observation(command, stdout, stderr, exit_code)  # type: ignore[return-value]

    def _session_ready(self) -> bool:
        return self._initialized and not self._closed

    def _session_not_ready_observation(self) -> ErrorObservation:
        return ErrorObservation(
            content="PowerShell session is not initialized or has been closed."
        )
