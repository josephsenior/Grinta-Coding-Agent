"""This module provides a Windows-specific implementation for running commands in PowerShell.

Uses subprocess calls to pwsh.exe (PowerShell 7) or powershell.exe (Windows PowerShell).
This is simpler and more reliable than using the .NET SDK via pythonnet.
"""

from __future__ import annotations

import sys

# CRITICAL: Platform check MUST be the very first thing after imports
if sys.platform != 'win32':

    class WindowsOnlyModuleError(RuntimeError):
        """Raised when Windows-specific module functionality is accessed on unsupported platforms."""

        def __init__(self, module: str):
            super().__init__(
                f'FATAL ERROR: This module ({module}) requires Windows platform, '
                f'but is running on {sys.platform}. This should never happen and indicates a '
                f'serious configuration issue. Please use the appropriate platform-specific runtime.'
            )

    raise WindowsOnlyModuleError('windows_bash.py')

import os
import re
import subprocess
from threading import RLock
from typing import TYPE_CHECKING

from backend.core.logger import app_logger as logger
from backend.execution.utils.process_registry import TaskCancellationService
from backend.ledger.observation import ErrorObservation
from backend.ledger.observation.commands import (
    CmdOutputMetadata,
    CmdOutputObservation,
)


# ``Start-Process`` detaches a new process tree from our subprocess. Because
# the PowerShell host returns as soon as the detach completes, the Popen PID
# we register with ``TaskCancellationService`` is the (already-exited) shell
# — not the python / node / whatever child that's actually listening on a
# port. When the session ends we'd leak that child.
#
# We detect bare ``Start-Process`` invocations (word boundary, case-insensitive,
# skipping occurrences inside quoted strings is not worth the complexity — a
# false positive just means one extra ``Get-Process`` call) and wrap the whole
# command in a before/after PID diff. Any newly-appeared PID is reported back
# via an ASCII sentinel on stdout, which we parse out and register for
# eventual cleanup.
_START_PROCESS_RE = re.compile(r'(?i)(?<![A-Za-z0-9_-])Start-Process(?![A-Za-z0-9_-])')
_SPAWNED_PID_MARKER_RE = re.compile(
    r'___GRINTA_SPAWNED___([^_]*?)___END___\r?\n?'
)

if TYPE_CHECKING:
    from backend.ledger.action import CmdRunAction


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
            ['pwsh', '-NoProfile', '-Command', '$PSVersionTable.PSVersion'],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            logger.info('Found PowerShell 7 (pwsh.exe)')
            return 'pwsh'
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Fall back to Windows PowerShell
    try:
        result = subprocess.run(
            ['powershell', '-NoProfile', '-Command', '$PSVersionTable.PSVersion'],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            logger.info('Found Windows PowerShell (powershell.exe)')
            return 'powershell'
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    raise RuntimeError(
        'PowerShell is required on Windows but could not be found. '
        'Please install PowerShell 7 (https://aka.ms/powershell) or ensure Windows PowerShell is available.'
    )


from backend.execution.utils.unified_shell import BaseShellSession  # noqa: E402


def _wrap_command_for_spawn_tracking(command: str) -> str:
    """Wrap a PowerShell command so newly-spawned PIDs get reported back.

    The wrapper snapshots the set of visible process IDs before the user
    command runs and again in a ``finally`` block afterwards, emitting the
    diff on stdout inside a sentinel (``___GRINTA_SPAWNED___<ids>___END___``).
    Using ``finally`` ensures we still report spawned children when the user
    command errors — important because a failed ``Start-Process`` invocation
    can leave partial leftovers.

    We deliberately avoid PowerShell string-escape gymnastics by relying on
    script-block invocation (``& { ... }``); the user command is embedded
    literally via a here-string so quotes, backticks, and variable refs in
    the original command behave exactly as they would if we hadn't wrapped.
    """
    # Use a here-string so any quote characters in ``command`` are preserved
    # without needing escapes. The trailing ``\n'@`` terminator must sit on
    # its own line per PowerShell syntax.
    here_string = f"@'\n{command}\n'@"
    return (
        '$__grinta_before = @(Get-Process -ErrorAction SilentlyContinue '
        '| Select-Object -ExpandProperty Id); '
        'try { '
        f'Invoke-Expression -Command ({here_string}) '
        '} finally { '
        '$__grinta_after = @(Get-Process -ErrorAction SilentlyContinue '
        '| Select-Object -ExpandProperty Id); '
        '$__grinta_new = @($__grinta_after '
        '| Where-Object { $__grinta_before -notcontains $_ }); '
        'if ($__grinta_new.Count -gt 0) { '
        "Write-Output ('___GRINTA_SPAWNED___' "
        "+ ($__grinta_new -join ',') + '___END___') "
        '} '
        '}'
    )


def _extract_spawned_pids(stdout: str) -> tuple[str, list[int]]:
    """Pull the spawn-tracking sentinel out of stdout and return (clean, pids).

    The sentinel is always the *last* line emitted because it comes from the
    ``finally`` block of :func:`_wrap_command_for_spawn_tracking`. We strip
    every match — not just the last — to be defensive against nested
    wrappers or partial user scripts that happen to echo the marker back.
    """
    if '___GRINTA_SPAWNED___' not in stdout:
        return stdout, []

    pids: list[int] = []
    for match in _SPAWNED_PID_MARKER_RE.finditer(stdout):
        raw = match.group(1)
        for chunk in raw.split(','):
            chunk = chunk.strip()
            if chunk.isdigit():
                pids.append(int(chunk))

    cleaned = _SPAWNED_PID_MARKER_RE.sub('', stdout)
    # The sentinel is emitted by Write-Output which inserts a newline; trim
    # any trailing blank line the substitution leaves behind so the visible
    # output looks identical to the unwrapped case.
    return cleaned.rstrip('\r\n') + ('\n' if stdout.endswith('\n') else ''), pids


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
                logger.info('Created working directory: %s', self._cwd)
            self._initialized = True
            logger.info(
                'PowerShell session initialized. Using: %s, Initial CWD: %s',
                self.powershell_exe,
                self._cwd,
            )
        except Exception as e:
            logger.error('Failed to initialize PowerShell session: %s', e)
            self.close()
            raise RuntimeError(f'Failed to initialize PowerShell session: {e}') from e

    def initialize(self) -> None:
        """Initialize the session (already done in __init__).

        This method is provided for compatibility with the base ShellSession interface.
        """
        if not self._initialized:
            raise RuntimeError('PowerShell session failed to initialize in __init__')

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
            raise RuntimeError('PowerShell session is closed')

        work_dir = cwd or self._cwd
        if not os.path.isdir(work_dir):
            work_dir = self.work_dir

        # If the command detaches a process tree via Start-Process, wrap it
        # so we can register the orphaned children for later cleanup. The
        # original command is preserved verbatim inside the wrapper so
        # syntax / variable scoping behave identically.
        wrapped_for_spawn_tracking = _START_PROCESS_RE.search(command) is not None
        effective_command = (
            _wrap_command_for_spawn_tracking(command)
            if wrapped_for_spawn_tracking
            else command
        )

        # Build PowerShell command
        # Use -NoProfile for faster startup, -Command to execute
        ps_command = [
            self.powershell_exe,
            '-NoProfile',
            '-NonInteractive',
            '-Command',
            effective_command,
        ]

        process = None
        try:
            # Child Python tools (uv/uvx/pip) often print UTF-8 symbols; without this,
            # Windows defaults (cp1252) raise UnicodeEncodeError inside the child.
            child_env = os.environ.copy()
            child_env.setdefault('PYTHONIOENCODING', 'utf-8')
            child_env.setdefault('PYTHONUTF8', '1')
            # Use Popen instead of run to capture PID for cancellation service
            process = subprocess.Popen(
                ps_command,
                cwd=work_dir,
                env=child_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE if input_text is not None else None,
                text=True,
                encoding='utf-8',
                errors='replace',
            )

            # Register for cancellation
            self._cancellation.register_process(process)

            stdout, stderr = process.communicate(input=input_text, timeout=timeout)
            return_code = process.returncode

            # Update CWD if command changed directory
            if 'cd ' in command.lower() or 'Set-Location' in command:
                self._update_cwd_from_output(  # type: ignore[attr-defined]
                    [
                        self.powershell_exe,
                        '-NoProfile',
                        '-Command',
                        'Get-Location | Select-Object -ExpandProperty Path',
                    ]
                )

            if wrapped_for_spawn_tracking:
                stdout, new_pids = _extract_spawned_pids(stdout)
                for pid in new_pids:
                    # Skip the PowerShell host PID we already track via the
                    # Popen handle — it's about to exit anyway.
                    if pid == process.pid:
                        continue
                    self._cancellation.register_pid(pid)
                if new_pids:
                    logger.info(
                        'Start-Process wrapper registered %d spawned pid(s) '
                        'for session cleanup: %s',
                        len(new_pids),
                        new_pids,
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
                '-NoProfile',
                '-Command',
                'Get-Location | Select-Object -ExpandProperty Path',
            ]
        )

    def _handle_timeout_exception(
        self, process: subprocess.Popen | None, timeout: int | None, command: str
    ) -> tuple[str, str, int]:
        """Handle subprocess timeout."""
        logger.warning('Command timed out after %s seconds: %s', timeout, command)
        if process:
            try:
                process.kill()
                process.wait()
            except Exception:
                pass
        return ('', f'Command timed out after {timeout} seconds', 124)

    def _handle_run_exception(
        self, process: subprocess.Popen | None, e: Exception
    ) -> tuple[str, str, int]:
        """Handle general subprocess exceptions."""
        logger.error('Error running PowerShell command: %s', e)
        if process:
            try:
                process.kill()
            except Exception:
                pass
        return ('', str(e), 1)

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
            'Write-Output $p.Id'
        )
        stdout, stderr, exit_code = self._run_command(start_proc, timeout=10)
        if exit_code == 0 and stdout.strip().isdigit():
            child_pid = int(stdout.strip())
            logger.info('Background process started with PID: %s', child_pid)
            self._cancellation.register_pid(child_pid)
            metadata = CmdOutputMetadata(
                exit_code=0,
                working_dir=self._cwd.replace('\\', '\\\\'),
            )
            return CmdOutputObservation(
                content=f'[{child_pid}]',
                command=command,
                metadata=metadata,
            )

        # Fallback: run normally if background start fails
        logger.warning('Failed to start background job, running normally')
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
            content='PowerShell session is not initialized or has been closed.'
        )

    def read_output(self) -> str:
        """Read pending output from the shell session."""
        # Not supported in current Windows implementation (subprocess-based)
        return ''

    def write_input(self, data: str, is_control: bool = False) -> None:
        """Write input to the shell session."""
        # Not supported in current Windows implementation (subprocess-based)
        logger.warning(
            'Terminal input not supported on Windows subprocess implementation'
        )
