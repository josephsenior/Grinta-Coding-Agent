"""_AesIoRunMixin: extracted from action_execution_server_io.

Split of the original RuntimeExecutorIOAndTerminalMixin to keep the
parent module under the per-file LOC budget. Pure code motion —
method bodies are byte-identical to the pre-split version.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from backend.core.logger import app_logger as logger
from backend.execution.aes.file_operations import (
    truncate_cmd_output,
)
from backend.execution.aes.helpers import (
    apply_grep_filter as _apply_grep_filter_impl,
)
from backend.execution.aes.helpers import (
    apply_terminal_resize_if_requested as _apply_terminal_resize_if_requested_impl,
)
from backend.execution.aes.helpers import (
    attach_detected_server as _attach_detected_server_impl,
)
from backend.execution.utils.shell.unified_shell import BaseShellSession
from backend.ledger.action import (
    CmdRunAction,
    DebuggerAction,
)
from backend.ledger.observation import (
    CmdOutputObservation,
    ErrorObservation,
    Observation,
)
from backend.ledger.observation.terminal import TerminalObservation
from backend.utils.async_helpers.async_utils import call_sync_from_async

if TYPE_CHECKING:
    pass


class _AesIoRunMixin:
    """Mixin extracted from RuntimeExecutorIOAndTerminalMixin."""

    async def run(
        self, action: CmdRunAction
    ) -> CmdOutputObservation | ErrorObservation | TerminalObservation:
        """Execute bash/shell command."""
        try:
            if self._should_rewrite_python3_to_python() and action.command:
                action.command = re.sub(r'\bpython3\b', 'python', action.command)

            default_session = self.session_manager.get_session('default')
            base_cwd = default_session.cwd if default_session else self._initial_cwd
            cwd_error = self._validate_workspace_scoped_cwd(
                action.command,
                action.cwd,
                base_cwd,
            )
            if cwd_error is not None:
                return cwd_error

            if action.is_background:
                return await self._run_background_cmd(action)

            observation = await self._run_foreground_cmd(action)
            if isinstance(observation, ErrorObservation):
                return observation

            return self._post_process_run_observation(action, observation)
        except Exception as exc:
            logger.error('Error running command: %s', exc)
            return ErrorObservation(str(exc))

    def _post_process_run_observation(
        self, action: CmdRunAction, observation: CmdOutputObservation
    ) -> CmdOutputObservation | ErrorObservation | TerminalObservation:
        if action.grep_pattern and isinstance(observation.content, str):
            observation.content = self._apply_grep_filter(
                observation.content, action.grep_pattern
            )
        if isinstance(observation.content, str):
            observation.content = truncate_cmd_output(observation.content)

        self._annotate_environment_errors(observation)

        if not action.is_static:
            self._attach_detected_server(
                observation, self.session_manager.get_session('default')
            )

        return observation

    async def _run_background_cmd(self, action: CmdRunAction) -> TerminalObservation:
        session_id = f'bg-{uuid.uuid4().hex[:8]}'
        default_session = self.session_manager.get_session('default')
        cwd = str(
            self._resolve_effective_cwd(
                action.cwd,
                (default_session.cwd if default_session else None) or self._initial_cwd,
            )
        )
        session = self.session_manager.create_session(session_id=session_id, cwd=cwd)
        logger.debug(
            'Starting background task in session %s: %s', session_id, action.command
        )
        session.write_input(action.command + '\n')
        await asyncio.sleep(0.5)
        content = session.read_output()
        return TerminalObservation(
            session_id=session_id,
            content=f'Background task started. Session ID: {session_id}\nInitial Output:\n{content}',
        )

    async def debugger(self, action: DebuggerAction) -> Observation:
        # ``DAPDebugManager.handle`` is fully synchronous: it spawns a
        # ``debugpy.adapter`` subprocess and performs blocking ``queue.get``
        # waits on DAP responses. Running it directly on the event loop
        # blocks every other coroutine for the duration of the cold start.
        # Off-load to a worker thread so the loop stays responsive.
        logger.debug(
            'Runtime debugger bridge invoking handle',
            extra={
                'msg_type': 'DEBUGGER_BRIDGE',
                'debug_action': getattr(action, 'debug_action', None),
                'cwd': str(Path.cwd()),
            },
        )
        return await asyncio.to_thread(self.debug_manager.handle, action)

    def _maybe_promote_blocking_action(self, action: CmdRunAction) -> None:
        try:
            from backend.execution.utils.shell.blocking_heuristics import (
                is_known_slow_command,
            )

            command = getattr(action, 'command', '') or ''
            if not getattr(action, 'blocking', False) and is_known_slow_command(
                command
            ):
                action.blocking = True  # type: ignore[attr-defined]
                logger.info(
                    'Auto-promoted blocking=True for slow command: %s',
                    command.splitlines()[0][:120],
                )
        except Exception:
            logger.debug('blocking-heuristic check failed', exc_info=True)

    @staticmethod
    def _set_pending_background_id(bash_session: BaseShellSession, bg_id: str) -> None:
        if hasattr(bash_session, '_pending_bg_id'):
            bash_session._pending_bg_id = bg_id  # type: ignore[union-attr]

    @staticmethod
    def _clear_pending_background_id(bash_session: BaseShellSession) -> None:
        if hasattr(bash_session, '_pending_bg_id'):
            bash_session._pending_bg_id = None  # type: ignore[union-attr]

    def _register_detached_pane_background(
        self,
        bash_session: BaseShellSession,
        registered_bg_id: str | None,
    ) -> Any:
        detached_pane = getattr(bash_session, '_detached_pane', None)
        detached_window = getattr(bash_session, '_detached_window', None)
        if detached_pane is None or detached_window is None or registered_bg_id is None:
            return detached_pane

        from backend.execution.utils.shell.bash import BackgroundPaneSession

        bg_pane_session = BackgroundPaneSession(
            pane=detached_pane,
            window=detached_window,
            cwd=str(getattr(bash_session, '_cwd', None) or self._initial_cwd),
        )
        self.session_manager.sessions[registered_bg_id] = bg_pane_session
        logger.info(
            'Registered background pane session %s after idle-timeout detach',
            registered_bg_id,
        )
        bash_session._detached_pane = None
        bash_session._detached_window = None
        bash_session._bg_session_id = None
        return detached_pane

    def _register_detached_subprocess_background(
        self,
        bash_session: BaseShellSession,
        registered_bg_id: str | None,
        detached_pane: Any,
    ) -> None:
        bg_process = getattr(bash_session, '_bg_process', None)
        bg_sub_id = getattr(bash_session, '_bg_session_id', None) or registered_bg_id
        bg_stdout_cap = getattr(bash_session, '_bg_stdout_capture', None)
        if (
            bg_process is None
            or bg_sub_id is None
            or bg_stdout_cap is None
            or detached_pane is not None
        ):
            return

        from backend.execution.utils.shell.subprocess_background import (
            SubprocessBackgroundSession,
        )

        bg_sub_session = SubprocessBackgroundSession(
            process=bg_process,
            stdout_capture=bg_stdout_cap,
            stderr_capture=getattr(bash_session, '_bg_stderr_capture', None),
            cwd=str(getattr(bash_session, '_cwd', None) or self._initial_cwd),
        )
        self.session_manager.sessions[bg_sub_id] = bg_sub_session
        logger.info(
            'Registered subprocess background session %s after idle-timeout detach',
            bg_sub_id,
        )
        bash_session._bg_process = None
        bash_session._bg_session_id = None
        bash_session._bg_stdout_capture = None
        bash_session._bg_stderr_capture = None

    async def _run_foreground_cmd(
        self, action: CmdRunAction
    ) -> CmdOutputObservation | ErrorObservation:
        if action.is_static:
            return await self._run_static_cmd(action)
        try:
            self.session_manager.cleanup_idle_sessions(max_idle_seconds=3600)
        except Exception:
            logger.debug('cleanup_idle_sessions failed', exc_info=True)
        bash_session, shell_err = self._get_or_recreate_default_shell_session()
        if shell_err is not None:
            return shell_err
        assert bash_session is not None

        self._maybe_promote_blocking_action(action)

        bg_id = f'bg-{uuid.uuid4().hex[:8]}'
        self._set_pending_background_id(bash_session, bg_id)
        try:
            observation = cast(
                CmdOutputObservation,
                await call_sync_from_async(bash_session.execute, action),
            )
        finally:
            self._clear_pending_background_id(bash_session)

        registered_bg_id = getattr(bash_session, '_bg_session_id', None)
        detached_pane = self._register_detached_pane_background(
            bash_session,
            registered_bg_id,
        )
        self._register_detached_subprocess_background(
            bash_session,
            registered_bg_id,
            detached_pane,
        )

        return observation

    async def _run_static_cmd(
        self, action: CmdRunAction
    ) -> CmdOutputObservation | ErrorObservation:
        temp_id = f'static-{uuid.uuid4().hex[:8]}'
        default_session = self.session_manager.get_session('default')
        cwd = str(
            self._resolve_effective_cwd(
                action.cwd,
                (default_session.cwd if default_session else None) or self._initial_cwd,
            )
        )
        bash_session = self.session_manager.create_session(session_id=temp_id, cwd=cwd)
        try:
            return cast(
                CmdOutputObservation,
                await call_sync_from_async(bash_session.execute, action),
            )
        finally:
            self.session_manager.close_session(temp_id)

    def _apply_grep_filter(self, content: str, pattern_str: str) -> str:
        return _apply_grep_filter_impl(content, pattern_str)

    def _attach_detected_server(
        self, observation: CmdOutputObservation, bash_session: Any
    ) -> None:
        _attach_detected_server_impl(self, observation, bash_session)

    def _apply_terminal_resize_if_requested(
        self, session: Any, rows: int | None, cols: int | None
    ) -> ErrorObservation | None:
        return _apply_terminal_resize_if_requested_impl(self, session, rows, cols)
