"""Simple Bash session using subprocess (no tmux required).

Provides Bash command execution without tmux dependency.
Useful for systems that have Bash but not tmux installed.
"""

from __future__ import annotations

import os
import subprocess
from typing import TYPE_CHECKING

from backend.core.logger import app_logger as logger
from backend.execution.utils.bounded_io import bounded_communicate
from backend.ledger.observation import ErrorObservation
from backend.ledger.observation.commands import (
    CmdOutputMetadata,
    CmdOutputObservation,
)

if TYPE_CHECKING:
    from backend.ledger.action import CmdRunAction


from backend.execution.utils.unified_shell import BaseShellSession


class SimpleBashSession(BaseShellSession):
    """Bash session using simple subprocess calls (no tmux).

    This is a fallback for systems that have Bash but not tmux.
    It's simpler but lacks some features like background job management.
    """

    def initialize(self) -> None:
        """Initialize the session."""
        logger.info(
            'Initializing SimpleBashSession (no tmux). Work dir: %s',
            self.work_dir,
        )
        # Verify working directory exists
        if not os.path.isdir(self._cwd):
            os.makedirs(self._cwd, exist_ok=True)
            logger.info('Created working directory: %s', self._cwd)

        self._initialized = True
        logger.info('SimpleBashSession initialized successfully')

    def execute(self, action: CmdRunAction) -> CmdOutputObservation | ErrorObservation:
        """Execute a command in Bash."""
        if not self._initialized or self._closed:
            return ErrorObservation(
                content='Bash session is not initialized or has been closed.'
            )

        command = action.command.strip()
        timeout_seconds = self._normalize_timeout(action.timeout)  # type: ignore[arg-type]

        if action.is_input:
            return ErrorObservation(
                content='Interactive input not supported in SimpleBashSession. '
                'Use tmux-based BashSession for interactive commands.'
            )

        # Handle background commands (ending with &)
        command, run_in_background = self._prepare_command(command)

        logger.info(
            "Executing command: '%s', Timeout: %ss, background: %s",
            command,
            timeout_seconds,
            run_in_background,
        )

        if run_in_background:
            return self._handle_background_execution(command)

        # If the action server armed a background-detach ID, use the
        # idle-output–aware monitoring path so slow commands are kept alive
        # rather than killed on timeout.
        pending_bg_id = self._pending_bg_id
        if pending_bg_id is not None:
            process = self._start_subprocess(command)
            out, err, code = self._run_backgroundable(
                process, timeout_seconds, pending_bg_id
            )
            if code == -2:
                # Process was detached to a background session.
                # action_execution_server will pick up _bg_process and register it.
                from backend.ledger.observation.commands import (
                    CmdOutputMetadata,
                    CmdOutputObservation,
                )

                metadata = CmdOutputMetadata(exit_code=-2, working_dir=self._cwd)
                metadata.suffix = (
                    f'\n[The command has no new output after {self.NO_CHANGE_TIMEOUT_SECONDS} seconds. '
                    f'It is still running in background session "{pending_bg_id}". '
                    f'Use terminal_read(session_id="{pending_bg_id}") to poll for new output, '
                    f'or terminal_read(session_id="{pending_bg_id}", mode="snapshot") for the full buffer. '
                    f'When the command completes, the session will show an exit indicator.]'
                )
                return CmdOutputObservation(
                    content=out, command=command, metadata=metadata
                )
            if process.pid:
                self._cancellation.unregister_process(process.pid)
            return self._format_execution_observation(  # type: ignore[return-value]
                command, out, err, code
            )

        # Regular foreground command (original path)
        stdout, stderr, exit_code = self._run_command(command, timeout=timeout_seconds)
        return self._format_execution_observation(command, stdout, stderr, exit_code)  # type: ignore[return-value]

    def _handle_background_execution(
        self, command: str
    ) -> CmdOutputObservation | ErrorObservation:
        """Handle execution of background commands via nohup."""
        bg_command = f'nohup {command} > /dev/null 2>&1 & echo $!'
        stdout, stderr, exit_code = self._run_command(bg_command, timeout=10)

        if exit_code == 0 and stdout.strip().isdigit():
            pid = stdout.strip()
            logger.info('Background process started with PID: %s', pid)
            try:
                self._cancellation.register_pid(int(pid))
            except Exception:
                logger.debug('Failed to register background pid=%s', pid, exc_info=True)

            metadata = CmdOutputMetadata(exit_code=0, working_dir=self._cwd)
            return CmdOutputObservation(
                content=f'[{pid}]',
                command=command,
                metadata=metadata,
            )

        logger.warning('Failed to start background process, running normally')
        # Fallback to foreground execution if background start fails
        stdout, stderr, exit_code = self._run_command(command, timeout=60)
        return self._format_execution_observation(command, stdout, stderr, exit_code)  # type: ignore[return-value]

    def _run_command(
        self,
        command: str,
        timeout: int | None = None,
    ) -> tuple[str, str, int]:
        """Run a Bash command via subprocess with bounded stdout/stderr.

        Uses ``bounded_communicate`` instead of the stdlib ``communicate``
        so a runaway child cannot exhaust agent memory before per-observation
        truncation kicks in.
        """
        if self._closed:
            raise RuntimeError('Bash session is closed')

        process = None
        try:
            process = self._start_subprocess(command)
            result = bounded_communicate(process, timeout=timeout)

            if self._command_changes_cwd(command):
                self._update_cwd_if_needed()

            if result.timed_out:
                logger.warning(
                    'Command timed out after %s seconds: %s', timeout, command
                )
                return ('', f'Command timed out after {timeout} seconds', 124)

            return (result.stdout, result.stderr, result.returncode)

        except subprocess.TimeoutExpired:
            return self._handle_subprocess_timeout(command, timeout)
        except Exception as e:
            logger.error('Error running Bash command: %s', e)
            return ('', str(e), 1)
        finally:
            if process is not None and process.pid:
                self._cancellation.unregister_process(process.pid)

    def _start_subprocess(self, command: str) -> subprocess.Popen:
        """Initialize and register the subprocess.

        Note: stdout/stderr are kept in **binary** mode here so that
        ``bounded_communicate`` can enforce a precise byte cap. Decoding to
        UTF-8 (with ``errors='replace'``) happens in the bounded reader.
        """
        argv = self._wrap_subprocess_argv(['bash', '-c', command], cwd=self._cwd)
        process = subprocess.Popen(
            argv,
            cwd=self._cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._cancellation.register_process(process)
        return process

    def _update_cwd_if_needed(self) -> None:
        """Update current working directory by querying the shell."""
        self._update_cwd_from_output(['bash', '-c', 'pwd'])

    def _handle_subprocess_timeout(
        self, command: str, timeout: int | None
    ) -> tuple[str, str, int]:
        """Handle subprocess timeout and ensure cleanup."""
        logger.warning('Command timed out after %s seconds: %s', timeout, command)
        # Process cleanup is handled by cancellation service if registered,
        # but we also attempt a direct kill here for safety.
        return ('', f'Command timed out after {timeout} seconds', 124)

    def write_input(self, data: str, is_control: bool = False) -> None:
        """Write input to the shell session."""
        # Not supported as commands are executed via subprocess
        logger.warning('Terminal input not supported in SimpleBashSession (no tmux)')
