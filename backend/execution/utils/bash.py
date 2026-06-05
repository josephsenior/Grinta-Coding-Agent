"""Utilities for executing and monitoring bash commands within runtime sessions."""

from __future__ import annotations

import os
import re
import time
import uuid
from enum import Enum
from typing import TYPE_CHECKING

import libtmux

from backend.core.logger import app_logger as logger
from backend.execution.utils._bash_command import (
    _check_command_completion,
    _combine_outputs_between_matches,
    _handle_interactive_prompts,
    _is_special_key,
    _validate_session_and_command,
)
from backend.execution.utils._bash_command import execute as _execute
from backend.execution.utils._bash_detached import (
    _clear_detached_target,
    _create_detached_foreground_window,
    _detach_pane_to_background,
    _initialize_detached_foreground,
    _live_cwd_for_detach,
    _set_detached_target,
)
from backend.execution.utils._bash_pane import (
    _clear_screen,
    _ensure_session_alive,
    _get_command_output,
    _get_pane_content,
    _get_window_and_pane_with_retry,
    _hard_kill_tmux_session,
    _prepare_tmux_tmpdir,
    _ready_for_next_command,
    _require_pane,
    _send_command_to_pane,
    _should_use_su,
    _update_cwd,
)
from backend.execution.utils._bash_server import (
    _detect_server_startup,
)
from backend.execution.utils._bash_server import (
    get_detected_server as _get_detected_server,
)
from backend.execution.utils._bash_timeouts import (
    _check_timeouts,
    _handle_completed_command,
    _handle_hard_timeout_command,
    _handle_nochange_timeout_command,
    _handle_previous_command_timeout,
    _kill_hung_process,
    _monitor_command_execution,
)
from backend.execution.utils.bash_support import (
    BackgroundPaneSession as _BackgroundPaneSession,
)
from backend.execution.utils.bash_support import (  # noqa: F401
    escape_bash_special_chars,  # re-exported for public API
    remove_command_prefix,
    split_bash_commands,  # re-exported for public API
)
from backend.execution.utils.prompt_detector import (
    detect_interactive_prompt,  # noqa: F401
)
from backend.execution.utils.unified_shell import BaseShellSession
from backend.ledger.observation import ErrorObservation
from backend.ledger.observation.commands import (
    CMD_OUTPUT_PS1_END,  # noqa: F401
    CmdOutputMetadata,
    CmdOutputObservation,
)
from backend.utils.shutdown_listener import should_continue  # noqa: F401

if TYPE_CHECKING:
    from libtmux.pane import Pane
    from libtmux.server import Server
    from libtmux.session import Session
    from libtmux.window import Window

    from backend.execution.utils.process_registry import TaskCancellationService
    from backend.ledger.action import CmdRunAction

Ps1Match = re.Match[str]
_remove_command_prefix = remove_command_prefix
BackgroundPaneSession = _BackgroundPaneSession


def _matches_ps1_metadata(pane_content: str) -> list[Ps1Match]:
    return CmdOutputMetadata.matches_ps1_metadata(pane_content)


def _call_uid_getter(uid_getter) -> int:
    return uid_getter()


class BashCommandStatus(Enum):
    """State machine statuses emitted while monitoring bash command execution."""

    CONTINUE = 'continue'
    COMPLETED = 'completed'
    NO_CHANGE_TIMEOUT = 'no_change_timeout'
    HARD_TIMEOUT = 'hard_timeout'


class BashSession(BaseShellSession):
    """Manage a tmux-backed bash session for running agent commands."""

    POLL_INTERVAL = 0.5
    HISTORY_LIMIT = 10000
    PS1 = CmdOutputMetadata.to_ps1_prompt()

    _MAX_PANE_CAPTURE_CHARS = 200_000

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
        """Configure tmux-backed shell session defaults and resource limits."""
        super().__init__(
            work_dir=work_dir,
            username=username,
            no_change_timeout_seconds=no_change_timeout_seconds,
            max_memory_mb=max_memory_mb,
            cancellation_service=cancellation_service,
            security_config=security_config,
            workspace_root=workspace_root,
        )
        self._cancellation_callback_key: str | None = None
        self.server: Server | None = None
        self.session: Session | None = None
        self.window: Window | None = None
        self.pane: Pane | None = None
        self.prev_status: BashCommandStatus | None = None
        self.prev_output: str = ''
        self._detached_pane: Pane | None = None
        self._detached_window: Window | None = None

    def initialize(self) -> None:
        """Initialize tmux server and session for bash runtime."""
        self._prepare_tmux_tmpdir()
        try:
            server = libtmux.Server()
        except Exception as exc:
            raise RuntimeError(
                'Failed to initialize tmux server. Ensure tmux is installed and '
                'TMUX_TMPDIR is writable in this runtime.'
            ) from exc
        self.server = server
        _shell_command = '/bin/bash'
        if self._should_use_su():
            _shell_command = f'su {self.username} -'
        window_command = _shell_command
        logger.debug('Initializing bash session with command: %s', window_command)
        session_name = f'Grinta-{self.username}-{uuid.uuid4()}'
        session_obj = server.new_session(
            session_name=session_name,
            start_directory=self.work_dir,
            kill_session=True,
            attach=False,
            window_name='bash',
            window_command=window_command,
            x=1000,
            y=1000,
        )
        if session_obj is None:
            raise RuntimeError('Failed to create tmux session')
        session = session_obj
        self.session = session

        self._cancellation_callback_key = f'tmux-session:{session_name}'
        self._cancellation.register_kill_callback(
            self._cancellation_callback_key,
            self._hard_kill_tmux_session,
        )
        session.set_option('history-limit', str(self.HISTORY_LIMIT), _global=True)
        session.history_limit = str(self.HISTORY_LIMIT)
        window, pane = self._get_window_and_pane_with_retry(session)
        self.window = window
        self.pane = pane
        logger.debug('pane: %s; history_limit: %s', pane, session.history_limit)
        pane.send_keys(
            f'''export PROMPT_COMMAND='export PS1="{self.PS1}"'; export PS2=""'''
        )
        time.sleep(0.1)
        self._clear_screen()
        logger.debug('Bash session initialized with work dir: %s', self.work_dir)
        self._cwd = os.path.abspath(self.work_dir)
        self._initialized = True

    def close(self) -> None:
        """Clean up the session."""
        if self._closed:
            return
        logger.info('Closing BashSession...')
        if self._cancellation_callback_key:
            try:
                self._cancellation.unregister_kill_callback(
                    self._cancellation_callback_key
                )
            except Exception:
                logger.debug('Failed to unregister tmux kill callback', exc_info=True)
        session = self.session
        if session is not None:
            try:
                session.kill()
            except Exception:
                logger.debug('Failed to kill tmux session during close', exc_info=True)
        super().close()
        self._initialized = False
        logger.info('BashSession closed')

    @property
    def cwd(self) -> str:
        """Get current working directory for bash runtime."""
        return self._cwd

    def execute(self, action: CmdRunAction) -> CmdOutputObservation | ErrorObservation:
        """Execute a command in the bash session."""
        return _execute(self, action)

    def get_detected_server(self):
        """Get and clear the last detected server."""
        return _get_detected_server(self)

    def read_output(self) -> str:
        """Read pending output from the shell session."""
        try:
            return self._get_pane_content()
        except RuntimeError:
            return ''

    def write_input(self, data: str, is_control: bool = False) -> None:
        """Write input to the shell session."""
        pane = self._require_pane()
        if is_control:
            logger.debug('SENDING CONTROL INPUT: %s', data)
            pane.send_keys(data, enter=False)
        else:
            logger.debug('SENDING INPUT: %s', data)
            pane.send_keys(data, enter=True)

    def resize(self, rows: int, cols: int) -> None:
        """Resize the tmux pane to match a PTY (rows x columns in cells)."""
        pane = self.pane
        if pane is None:
            return
        try:
            pane.cmd('resize-pane', '-x', str(cols), '-y', str(rows))
        except Exception as exc:  # noqa: BLE001
            logger.debug('tmux resize-pane failed: %s', exc)

    def _prepare_tmux_tmpdir(self) -> None:
        return _prepare_tmux_tmpdir(self)

    def _hard_kill_tmux_session(self) -> None:
        return _hard_kill_tmux_session(self)

    def _ensure_session_alive(self) -> bool:
        return _ensure_session_alive(self)

    def _should_use_su(self) -> bool:
        return _should_use_su(self)

    def _update_cwd(self, output: str) -> None:
        return _update_cwd(self, output)

    def _get_pane_content(self) -> str:
        return _get_pane_content(self)

    def _get_window_and_pane_with_retry(
        self, session: Session, retries: int = 10, delay: float = 0.1
    ) -> tuple[Window, Pane]:
        return _get_window_and_pane_with_retry(self, session, retries, delay)

    def _require_pane(self) -> Pane:
        return _require_pane(self)

    def _is_special_key(self, command: str) -> bool:
        return _is_special_key(self, command)

    def _clear_screen(self) -> None:
        return _clear_screen(self)

    def _get_command_output(
        self,
        command: str,
        raw_command_output: str,
        metadata: CmdOutputMetadata,
        continue_prefix: str = '',
    ) -> str:
        return _get_command_output(self, command, raw_command_output, metadata, continue_prefix)

    def _handle_completed_command(
        self,
        command: str,
        pane_content: str,
        ps1_matches: list[Ps1Match],
        hidden: bool,
        is_input: bool = False,
    ) -> CmdOutputObservation:
        return _handle_completed_command(self, command, pane_content, ps1_matches, hidden, is_input)

    def _detach_pane_to_background(self, bg_session_id: str) -> None:
        return _detach_pane_to_background(self, bg_session_id)

    def _set_detached_target(self, bg_session_id: str) -> 'Session':
        return _set_detached_target(self, bg_session_id)

    def _clear_detached_target(self) -> None:
        return _clear_detached_target(self)

    def _live_cwd_for_detach(self) -> str:
        return _live_cwd_for_detach(self)

    def _create_detached_foreground_window(
        self,
        session: 'Session',
        live_cwd: str,
    ) -> tuple['Window', 'Pane']:
        return _create_detached_foreground_window(self, session, live_cwd)

    def _initialize_detached_foreground(
        self,
        new_window: 'Window',
        new_pane: 'Pane',
    ) -> None:
        return _initialize_detached_foreground(self, new_window, new_pane)

    def _kill_hung_process(self) -> None:
        return _kill_hung_process(self)

    def _handle_nochange_timeout_command(
        self,
        command: str,
        pane_content: str,
        ps1_matches: list[Ps1Match],
    ) -> CmdOutputObservation:
        return _handle_nochange_timeout_command(self, command, pane_content, ps1_matches)

    def _handle_hard_timeout_command(
        self,
        command: str,
        pane_content: str,
        ps1_matches: list[Ps1Match],
        timeout: float,
    ) -> CmdOutputObservation:
        return _handle_hard_timeout_command(self, command, pane_content, ps1_matches, timeout)

    def _ready_for_next_command(self) -> None:
        return _ready_for_next_command(self)

    def _combine_outputs_between_matches(
        self,
        pane_content: str,
        ps1_matches: list[Ps1Match],
        get_content_before_last_match: bool = False,
    ) -> str:
        return _combine_outputs_between_matches(self, pane_content, ps1_matches, get_content_before_last_match)

    def _validate_session_and_command(self, action: CmdRunAction) -> None:
        return _validate_session_and_command(self, action)

    def _handle_previous_command_timeout(
        self,
        command: str,
        last_pane_output: str,
        initial_ps1_matches: list[Ps1Match],
        is_input: bool,
    ) -> CmdOutputObservation | None:
        return _handle_previous_command_timeout(self, command, last_pane_output, initial_ps1_matches, is_input)

    def _send_command_to_pane(self, command: str, is_input: bool) -> None:
        return _send_command_to_pane(self, command, is_input)

    def _check_command_completion(
        self,
        cur_pane_output: str,
        ps1_matches: list[Ps1Match],
        initial_ps1_count: int,
        command: str,
        is_input: bool,
    ) -> CmdOutputObservation | None:
        return _check_command_completion(self, cur_pane_output, ps1_matches, initial_ps1_count, command, is_input)

    def _check_timeouts(
        self,
        action: CmdRunAction,
        last_change_time: float,
        start_time: float,
        command: str,
        cur_pane_output: str,
        ps1_matches: list[Ps1Match],
        first_output_seen: bool = True,
    ) -> CmdOutputObservation | None:
        return _check_timeouts(self, action, last_change_time, start_time, command, cur_pane_output, ps1_matches, first_output_seen)

    def _monitor_command_execution(
        self,
        command: str,
        initial_ps1_count: int,
        is_input: bool,
        action: CmdRunAction,
        initial_pane_output: str | None = None,
    ) -> CmdOutputObservation:
        return _monitor_command_execution(self, command, initial_ps1_count, is_input, action, initial_pane_output)

    def _handle_interactive_prompts(self, output: str, is_input: bool) -> bool:
        return _handle_interactive_prompts(self, output, is_input)

    def _detect_server_startup(self, output: str) -> None:
        return _detect_server_startup(self, output)
