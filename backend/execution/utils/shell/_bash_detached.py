"""Detached-session lifecycle helpers extracted from :class:`BashSession`.

When a foreground command is moved to the background, the active pane
must be replaced with a fresh one. These helpers coordinate that swap
and keep track of the detached window/pane for later polling.
"""

from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING, cast

from backend.core.logger import app_logger as logger

if TYPE_CHECKING:
    from libtmux.pane import Pane
    from libtmux.session import Session
    from libtmux.window import Window

    from backend.execution.utils.shell.bash import BashSession


def _set_detached_target(orch: BashSession, bg_session_id: str) -> 'Session':
    session = orch.session
    if session is None:
        raise RuntimeError('Cannot detach: tmux session is not initialized')

    orch._detached_pane = orch.pane
    orch._detached_window = orch.window
    orch._bg_session_id = bg_session_id
    return session


def _clear_detached_target(orch: BashSession) -> None:
    orch._detached_pane = None
    orch._detached_window = None
    orch._bg_session_id = None


def _live_cwd_for_detach(orch: BashSession) -> str:
    live_cwd = orch._cwd
    try:
        pane_for_query = orch._detached_pane
        if pane_for_query is None:
            return live_cwd
        result = pane_for_query.cmd('display-message', '-p', '#{pane_current_path}')
        stdout_raw = getattr(result, 'stdout', None)
        stdout: list[str] = []
        if isinstance(stdout_raw, list):
            stdout_items = cast(list[object], stdout_raw)
            stdout = [item for item in stdout_items if isinstance(item, str)]
        if not stdout:
            return live_cwd
        candidate = stdout[0].strip()
        if not candidate or not os.path.isdir(candidate):
            return live_cwd
        if candidate != orch._cwd:
            logger.info(
                'Detach CWD updated from %s -> %s via tmux query',
                orch._cwd,
                candidate,
            )
            orch._cwd = candidate
        return candidate
    except Exception:
        logger.debug(
            'pane_current_path query failed before detach; using cached cwd',
            exc_info=True,
        )
        return live_cwd


def _create_detached_foreground_window(
    orch: BashSession,
    session: 'Session',
    live_cwd: str,
) -> tuple['Window', 'Pane']:
    new_window = session.new_window(
        window_name='bash',
        start_directory=live_cwd,  # type: ignore[arg-type]
        attach=False,
    )
    new_pane: Pane | None = None
    for _ in range(10):
        new_pane = getattr(new_window, 'active_pane', None)
        if new_pane is not None:
            return new_window, new_pane
        time.sleep(0.1)

    orch._clear_detached_target()
    raise RuntimeError('New tmux window has no active pane after retries')


def _initialize_detached_foreground(
    orch: BashSession,
    new_window: 'Window',
    new_pane: 'Pane',
) -> None:
    from backend.execution.utils.shell.bash import BashCommandStatus

    orch.window = new_window
    orch.pane = new_pane
    new_pane.send_keys(
        f'''export PROMPT_COMMAND='export PS1="{orch.PS1}"'; export PS2=""'''
    )
    time.sleep(0.1)
    orch._clear_screen()
    orch.prev_status = BashCommandStatus.COMPLETED


def _detach_pane_to_background(orch: BashSession, bg_session_id: str) -> None:
    """Keep the running process alive while detaching the current pane.

    After this call:
    - ``self.pane`` / ``self.window`` point to the new, idle window.
    - ``self._detached_pane`` / ``self._detached_window`` hold the old window
      so the action server can wrap them in a ``BackgroundPaneSession``.
    - ``self._bg_session_id`` is the new session ID for the caller to register.
    - ``self.prev_status`` is reset to ``COMPLETED`` so the next command runs
      normally on the fresh window.
    """
    session = _set_detached_target(orch, bg_session_id)
    live_cwd = _live_cwd_for_detach(orch)
    new_window, new_pane = _create_detached_foreground_window(orch, session, live_cwd)
    _initialize_detached_foreground(orch, new_window, new_pane)
    logger.info('Detached timed-out process to background session %s', bg_session_id)
