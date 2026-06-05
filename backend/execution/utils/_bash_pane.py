"""Pane and tmux infrastructure helpers extracted from :class:`BashSession`.

The functions in this module are the low-level pane operations shared by
timeout handling, command execution, and detached-session management.
They all take the ``BashSession`` instance as the first argument so the
class can stay a thin coordinator.
"""

from __future__ import annotations

import os
import shlex
import time
from typing import TYPE_CHECKING, Any, cast

import libtmux

from backend.core.logger import app_logger as logger
from backend.core.os_capabilities import OS_CAPS
from backend.execution.utils.bash_support import (
    escape_bash_special_chars,
    remove_command_prefix,
)

if TYPE_CHECKING:
    from libtmux.pane import Pane
    from libtmux.session import Session
    from libtmux.window import Window

    from backend.execution.utils.bash import BashSession
    from backend.ledger.observation.commands import CmdOutputMetadata

Ps1Match = Any  # alias: re.Match[str]


def _should_use_su(orch: BashSession) -> bool:
    """Determine if we should wrap shell command in ``su username -``."""
    username = orch.username
    if not username:
        return False
    if OS_CAPS.is_windows:
        return False
    try:
        uid_getter = getattr(os, 'geteuid', None)
        if uid_getter is None or not callable(uid_getter):
            return False
        uid = uid_getter()
    except (OSError, TypeError, ValueError):
        return False
    if uid != 0:
        return False
    import getpass

    current_user = None
    try:
        current_user = getpass.getuser()
    except Exception:
        logger.debug('Unable to determine current user for bash session')
    return current_user != username


def _update_cwd(orch: BashSession, output: str) -> None:
    """Update current working directory from command output."""
    orch._cwd = output


def _prepare_tmux_tmpdir(orch: BashSession) -> None:
    """Validate and prepare TMUX_TMPDIR when explicitly configured."""
    del orch  # instance kept for API uniformity; reads the env directly
    tmpdir = os.environ.get('TMUX_TMPDIR', '').strip()
    if not tmpdir:
        return
    try:
        os.makedirs(tmpdir, exist_ok=True)
    except OSError as exc:
        raise RuntimeError(f"TMUX_TMPDIR '{tmpdir}' could not be created") from exc
    if not os.access(tmpdir, os.W_OK):
        raise RuntimeError(f"TMUX_TMPDIR '{tmpdir}' is not writable")


def _hard_kill_tmux_session(orch: BashSession) -> None:
    session = orch.session
    if session is None:
        return
    try:
        session.kill()
    except Exception:
        logger.debug('Failed to kill tmux session', exc_info=True)


def _ensure_session_alive(orch: BashSession) -> bool:
    """Verify the tmux session is still alive; re-create if dead.

    Returns True if the session had to be recovered.
    """
    try:
        pane = orch.pane
        if pane is None:
            return False
        pane.cmd('display-message', '-p', '#{pane_pid}')
        return False
    except Exception:
        logger.warning('Tmux session died — attempting recovery')

    # Session is dead; re-initialize from scratch
    old_cwd = orch._cwd
    try:
        orch.initialize()
        new_pane = orch.pane
        if old_cwd and old_cwd != orch.work_dir and new_pane is not None:
            new_pane.send_keys(f'cd -- {shlex.quote(old_cwd)}')
            time.sleep(0.2)
            orch._clear_screen()
        logger.info('Tmux session recovered (cwd=%s)', old_cwd)
        return True
    except Exception as exc:
        logger.error('Tmux session recovery failed', exc_info=True)
        raise RuntimeError(
            'Tmux session died and could not be recovered. '
            'Check that tmux is running and TMUX_TMPDIR is writable.'
        ) from exc


def _get_window_and_pane_with_retry(
    orch: BashSession,
    session: Session,
    retries: int = 10,
    delay: float = 0.1,
) -> tuple[Window, Pane]:
    """Fetch the active tmux window and pane, retrying if tmux is still booting."""
    last_exc: Exception | None = None
    for attempt in range(retries):
        window = getattr(session, 'active_window', None)
        if window is None:
            time.sleep(delay)
            continue
        try:
            pane = getattr(window, 'active_pane', None)
        except libtmux.exc.LibTmuxException as exc:  # type: ignore[attr-defined]
            pane_lookup_error = cast(Exception, exc)
            last_exc = pane_lookup_error
            logger.debug(
                'Active pane lookup failed on attempt %s/%s: %s',
                attempt + 1,
                retries,
                pane_lookup_error,
            )
            time.sleep(delay)
            continue
        if pane is not None:
            return window, pane
        time.sleep(delay)
    raise RuntimeError('Window has no active pane') from last_exc


def _require_pane(orch: BashSession) -> Pane:
    pane = orch.pane
    if pane is None:
        raise RuntimeError('Bash session pane is not initialized')
    return pane


def _clear_screen(orch: BashSession) -> None:
    """Clear the tmux pane screen and history."""
    pane = orch._require_pane()
    pane.send_keys('C-l', enter=False)
    time.sleep(0.1)
    pane.cmd('clear-history')


def _get_pane_content(orch: BashSession) -> str:
    """Capture the current pane content and update the buffer.

    Limits capture to the last HISTORY_LIMIT lines via ``-S``
    and pre-truncates to ``_MAX_PANE_CAPTURE_CHARS`` to prevent
    regex backtracking on massive outputs.
    """
    pane = orch._require_pane()
    raw = '\n'.join(
        line.rstrip() for line in pane.cmd('capture-pane', '-J', '-pS', '-').stdout
    )
    if len(raw) > orch._MAX_PANE_CAPTURE_CHARS:
        # Keep the tail — PS1 prompt is always at the end.
        logger.warning(
            'Pane capture too large (%d chars), truncating to last %d chars',
            len(raw),
            orch._MAX_PANE_CAPTURE_CHARS,
        )
        raw = raw[-orch._MAX_PANE_CAPTURE_CHARS :]
    return raw


def _get_command_output(
    orch: BashSession,
    command: str,
    raw_command_output: str,
    metadata: CmdOutputMetadata,
    continue_prefix: str = '',
) -> str:
    """Get the command output with the previous command output removed."""
    if orch.prev_output:
        command_output = raw_command_output.removeprefix(orch.prev_output)
        metadata.prefix = continue_prefix
    else:
        command_output = raw_command_output
    orch.prev_output = raw_command_output
    command_output = remove_command_prefix(command_output, command)
    return command_output.rstrip()


def _send_command_to_pane(orch: BashSession, command: str, is_input: bool) -> None:
    """Send command or input to the pane."""
    pane = orch._require_pane()
    if is_input:
        is_special_key = orch._is_special_key(command)
        logger.debug('SENDING INPUT TO RUNNING PROCESS: %s', command)
        pane.send_keys(command, enter=not is_special_key)
    elif command != '':
        is_special_key = orch._is_special_key(command)
        command = escape_bash_special_chars(command)
        logger.debug('SENDING COMMAND: %s', command)
        pane.send_keys(command, enter=not is_special_key)


def _ready_for_next_command(orch: BashSession) -> None:
    """Reset the content buffer for a new command."""
    orch._clear_screen()
