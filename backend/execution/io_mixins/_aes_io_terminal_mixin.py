"""_AesIoTerminalMixin: extracted from action_execution_server_io.

Split of the original RuntimeExecutorIOAndTerminalMixin to keep the
parent module under the per-file LOC budget. Pure code motion —
method bodies are byte-identical to the pre-split version.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from backend.core.constants import (
    PTY_INPUT_READ_TIMEOUT_SECONDS,
    PTY_OPEN_READ_TIMEOUT_SECONDS,
    PTY_READ_POLL_INTERVAL_SECONDS,
    TERMINAL_EMPTY_READ_CLOSE_THRESHOLD,
    TERMINAL_RUN_EXECUTION_TIMEOUT_SECONDS,
)
from backend.core.logging.logger import app_logger as logger
from backend.execution.aes.helpers import (
    advance_terminal_read_cursor as _advance_terminal_read_cursor_impl,
)
from backend.execution.aes.helpers import (
    bump_terminal_empty_read_streak as _bump_terminal_empty_read_streak_impl,
)
from backend.execution.aes.helpers import (
    clear_terminal_read_cursor as _clear_terminal_read_cursor_impl,
)
from backend.execution.aes.helpers import (
    get_terminal_read_cursor as _get_terminal_read_cursor_impl,
)
from backend.execution.aes.helpers import (
    mark_terminal_session_interaction as _mark_terminal_session_interaction_impl,
)
from backend.execution.aes.helpers import (
    missing_terminal_session_error as _missing_terminal_session_error_impl,
)
from backend.execution.aes.helpers import (
    next_terminal_session_id as _next_terminal_session_id_impl,
)
from backend.execution.aes.helpers import (
    normalize_terminal_command as _normalize_terminal_command_impl,
)
from backend.execution.aes.helpers import (
    read_terminal_with_mode as _read_terminal_with_mode_impl,
)
from backend.execution.aes.helpers import (
    reset_terminal_empty_read_streak as _reset_terminal_empty_read_streak_impl,
)
from backend.execution.aes.helpers import (
    should_poll_terminal_input_delta as _should_poll_terminal_input_delta_impl,
)
from backend.execution.aes.helpers import (
    terminal_input_preflight_error as _terminal_input_preflight_error_impl,
)
from backend.execution.aes.helpers import (
    terminal_mode as _terminal_mode_impl,
)
from backend.execution.aes.helpers import (
    terminal_open_guardrail_error as _terminal_open_guardrail_error_impl,
)
from backend.execution.aes.helpers import (
    terminal_output_state as _terminal_output_state_impl,
)
from backend.execution.aes.helpers import (
    terminal_read_empty_hints as _terminal_read_empty_hints_impl,
)
from backend.execution.aes.helpers import (
    terminal_shell_kind as _terminal_shell_kind_impl,
)
from backend.execution.utils.shell.unified_shell import BaseShellSession
from backend.ledger.action.terminal import (
    TerminalCloseAction,
    TerminalInputAction,
    TerminalReadAction,
    TerminalRunAction,
)
from backend.ledger.observation import (
    ErrorObservation,
    Observation,
)
from backend.ledger.observation.terminal import TerminalObservation

if TYPE_CHECKING:
    pass


class _AesIoTerminalMixin:
    """Mixin extracted from RuntimeExecutorIOAndTerminalMixin."""

    def _next_terminal_session_id(self) -> str:
        return _next_terminal_session_id_impl(self)

    @staticmethod
    def _normalize_terminal_command(command: str) -> str:
        return _normalize_terminal_command_impl(command)

    def _mark_terminal_session_interaction(self, session_id: str) -> None:
        _mark_terminal_session_interaction_impl(self, session_id)

    def _terminal_open_guardrail_error(self, command: str) -> ErrorObservation | None:
        return _terminal_open_guardrail_error_impl(self, command)

    def _missing_terminal_session_error(
        self, session_id: str, *, operation: str
    ) -> ErrorObservation:
        return _missing_terminal_session_error_impl(
            self, session_id, operation=operation
        )

    @staticmethod
    def _terminal_mode(mode: str | None) -> str:
        return _terminal_mode_impl(mode)

    @staticmethod
    def _terminal_read_empty_hints(
        *, mode: str, has_new_output: bool
    ) -> dict[str, Any]:
        return _terminal_read_empty_hints_impl(mode=mode, has_new_output=has_new_output)

    @staticmethod
    def _terminal_shell_kind(session: Any) -> str:
        return _terminal_shell_kind_impl(session)

    @staticmethod
    def _terminal_input_preflight_error(
        command: str,
        *,
        shell_kind: str,
    ) -> ErrorObservation | None:
        return _terminal_input_preflight_error_impl(
            command,
            shell_kind=shell_kind,
        )

    @staticmethod
    def _terminal_output_state(
        content: str,
        *,
        default: str,
        shell_kind: str,
    ) -> str:
        return _terminal_output_state_impl(
            content,
            default=default,
            shell_kind=shell_kind,
        )

    @staticmethod
    def _should_poll_terminal_input_delta(session: Any) -> bool:
        return _should_poll_terminal_input_delta_impl(session)

    def _read_terminal_with_mode(
        self,
        *,
        session: Any,
        mode: str,
        offset: int | None,
    ) -> tuple[str, int | None, bool, int | None]:
        return _read_terminal_with_mode_impl(
            self,
            session=session,
            mode=mode,
            offset=offset,
        )

    def _get_terminal_read_cursor(self, session_id: str) -> int:
        return _get_terminal_read_cursor_impl(self, session_id)

    def _advance_terminal_read_cursor(
        self, session_id: str, next_offset: int | None, *, mode: str = 'delta'
    ) -> None:
        _advance_terminal_read_cursor_impl(self, session_id, next_offset, mode=mode)

    def _clear_terminal_read_cursor(self, session_id: str) -> None:
        _clear_terminal_read_cursor_impl(self, session_id)

    def _get_or_recreate_default_shell_session(
        self,
    ) -> tuple[BaseShellSession | None, ErrorObservation | None]:
        session = self.session_manager.get_session('default')
        if isinstance(session, BaseShellSession):
            return session, None
        if session is not None:
            return None, ErrorObservation(
                'Default shell session is not a foreground shell'
            )

        try:
            recreated = self.session_manager.create_session(session_id='default')
        except Exception as exc:
            logger.error(
                'Failed to recreate default shell session: %s', exc, exc_info=True
            )
            return (
                None,
                ErrorObservation(
                    'Default shell session not initialized (recreation failed).'
                ),
            )
        if not isinstance(recreated, BaseShellSession):
            return None, ErrorObservation(
                'Default shell session is not a foreground shell'
            )
        logger.warning('Recreated missing default shell session')
        return recreated, None

    def _log_terminal_debug(
        self, hypothesis_id: str, location: str, message: str, data: dict
    ) -> None:
        """Log debug trace for terminal operations."""
        try:
            payload = {
                'sessionId': 'fee086',
                'runId': 'pre-fix',
                'hypothesisId': hypothesis_id,
                'location': location,
                'message': message,
                'data': data,
                'timestamp': int(time.time() * 1000),
            }
            self._append_debug_trace(payload)
        except Exception:
            pass

    def _resolve_terminal_cwd(self, action_cwd: str | None) -> str:
        """Resolve effective working directory for terminal session."""
        default_session = self.session_manager.get_session('default')
        cwd = action_cwd
        if not cwd and default_session:
            cwd = default_session.cwd
        if not cwd:
            cwd = self._initial_cwd
        return str(self._resolve_effective_cwd(action_cwd, cwd))

    async def _poll_terminal_output(
        self,
        session: Any,
        offset: int,
        timeout: float,  # noqa: ASYNC109
    ) -> None:
        """Poll for terminal output with early exit on first byte."""
        poll_interval = PTY_READ_POLL_INTERVAL_SECONDS
        waited = 0.0
        while waited < timeout:
            await asyncio.sleep(poll_interval)
            waited += poll_interval
            probe, *_ = self._read_terminal_with_mode(
                session=session, mode='delta', offset=offset
            )
            if probe:
                break

    def _build_terminal_observation(
        self,
        session_id: str,
        content: str,
        next_offset: int,
        has_new_output: bool,
        dropped_chars: int,
        state: str,
        shell_kind: str,
        mode: str = 'delta',
    ) -> TerminalObservation:
        """Build TerminalObservation with tool_result metadata."""
        empty_hints = self._terminal_read_empty_hints(
            mode=mode, has_new_output=has_new_output
        )
        obs = TerminalObservation(
            session_id=session_id,
            content=content,
            next_offset=next_offset,
            has_new_output=has_new_output,
            dropped_chars=dropped_chars,
            state=state,
        )
        obs.tool_result = {
            'tool': 'terminal_manager',
            'ok': True,
            'error_code': None,
            'retryable': False,
            'state': state,
            'next_actions': ['read', 'input'],
            'payload': {
                'session_id': session_id,
                'shell_kind': shell_kind,
                'mode': mode,
                'next_offset': next_offset,
                'has_new_output': has_new_output,
                'dropped_chars': dropped_chars,
                **empty_hints,
            },
            'progress': bool(has_new_output),
        }
        return obs

    async def terminal_run(self, action: TerminalRunAction) -> Observation:
        try:
            return await asyncio.wait_for(
                self._terminal_run_impl(action),
                timeout=TERMINAL_RUN_EXECUTION_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning(
                'terminal_run exceeded %.0fs execution cap; closing partial session',
                TERMINAL_RUN_EXECUTION_TIMEOUT_SECONDS,
            )
            return ErrorObservation(
                content=(
                    f'TERMINAL_RUN_TIMEOUT: opening the interactive terminal exceeded '
                    f'{TERMINAL_RUN_EXECUTION_TIMEOUT_SECONDS:.0f}s. '
                    'The session was not opened successfully. Use execute_powershell '
                    'for one-shot commands, or retry terminal_manager action=open.'
                ),
                error_id='TERMINAL_RUN_TIMEOUT',
            )
        except Exception as exc:
            self._log_terminal_debug(
                'H9_terminal_run_exception',
                'backend/execution/action_execution_server_io.py:terminal_run',
                'terminal-run-exception',
                {'error': str(exc), 'error_type': type(exc).__name__},
            )
            logger.error('Error starting terminal session: %s', exc, exc_info=True)
            return ErrorObservation(f'Failed to start terminal: {exc}')

    async def _terminal_run_impl(self, action: TerminalRunAction) -> Observation:
        validation_error = self._terminal_run_validate(action)
        if validation_error is not None:
            return validation_error

        session_id = self._next_terminal_session_id()
        cwd = self._resolve_terminal_cwd(action.cwd)
        session = await asyncio.to_thread(
            self.session_manager.create_session,
            session_id=session_id,
            cwd=cwd,
            interactive=True,
        )
        shell_kind = self._terminal_shell_kind(session)

        resize_err = self._apply_terminal_resize_if_requested(
            session, action.rows, action.cols
        )
        if resize_err is not None:
            return self._terminal_run_resize_error(session_id, resize_err, action)

        if action.command:
            preflight_result = await self._terminal_run_preflight_and_execute(
                session, session_id, action, shell_kind, cwd
            )
            if preflight_result is not None:
                return preflight_result

        return self._terminal_run_build_observation(
            session, session_id, action, shell_kind
        )

    def _terminal_run_validate(
        self, action: TerminalRunAction
    ) -> ErrorObservation | None:
        guard_err = self._terminal_open_guardrail_error(action.command or '')
        if guard_err is not None:
            self._log_terminal_debug(
                'H7_terminal_run_branch',
                'backend/execution/action_execution_server_io.py:terminal_run',
                'terminal-run-guard-error',
                {'command': action.command or ''},
            )
            return guard_err

        cwd = self._resolve_terminal_cwd(action.cwd)
        cwd_error = self._validate_workspace_scoped_cwd(
            action.command or '<interactive terminal>',
            action.cwd,
            cwd,
        )
        if cwd_error is not None:
            self._log_terminal_debug(
                'H7_terminal_run_branch',
                'backend/execution/action_execution_server_io.py:terminal_run',
                'terminal-run-cwd-error',
                {'command': action.command or '', 'cwd': cwd},
            )
            return cwd_error
        return None

    def _terminal_run_resize_error(
        self, session_id: str, resize_err: ErrorObservation, action: TerminalRunAction
    ) -> ErrorObservation:
        self.session_manager.close_session(session_id)
        self._clear_terminal_read_cursor(session_id)
        self._log_terminal_debug(
            'H8_terminal_resize_branch',
            'backend/execution/action_execution_server_io.py:terminal_run',
            'terminal-run-resize-error',
            {'rows': action.rows, 'cols': action.cols},
        )
        return resize_err

    async def _terminal_run_preflight_and_execute(
        self,
        session: Any,
        session_id: str,
        action: TerminalRunAction,
        shell_kind: str,
        cwd: str,
    ) -> ErrorObservation | None:
        preflight_err = self._terminal_input_preflight_error(
            action.command,
            shell_kind=shell_kind,
        )
        if preflight_err is not None:
            self.session_manager.close_session(session_id)
            self._clear_terminal_read_cursor(session_id)
            preflight_err.tool_result = {
                'tool': 'terminal_manager',
                'ok': False,
                'error_code': 'TERMINAL_INPUT_PREFLIGHT_REJECTED',
                'retryable': True,
                'state': 'SESSION_NOT_OPENED',
                'payload': {
                    'session_id': session_id,
                    'shell_kind': shell_kind,
                    'command_was_sent': False,
                },
                'progress': False,
            }
            return preflight_err

        predicted_cwd, policy_error = self._evaluate_interactive_terminal_command(
            action.command,
            Path(cwd).resolve(),  # noqa: ASYNC240
        )
        if policy_error is not None:
            self.session_manager.close_session(session_id)
            self._clear_terminal_read_cursor(session_id)
            return policy_error
        logger.debug(
            'Running initial command in terminal %s: %s',
            session_id,
            action.command,
        )
        await asyncio.to_thread(session.write_input, action.command + '\n')
        if predicted_cwd is not None and hasattr(session, '_cwd'):
            session._cwd = str(predicted_cwd)  # type: ignore[attr-defined]

        await self._poll_terminal_output(session, 0, PTY_OPEN_READ_TIMEOUT_SECONDS)
        return None

    def _terminal_run_build_observation(
        self, session: Any, session_id: str, action: TerminalRunAction, shell_kind: str
    ) -> TerminalObservation:
        content, next_offset, has_new_output, dropped_chars = (
            self._read_terminal_with_mode(
                session=session,
                mode='delta',
                offset=0,
            )
        )
        state = self._terminal_output_state(
            content,
            default='SESSION_OPENED',
            shell_kind=shell_kind,
        )
        self._terminal_sessions_awaiting_interaction.append(session_id)
        self._terminal_open_commands_no_interaction.append(
            self._normalize_terminal_command(action.command or '')
        )
        obs = self._build_terminal_observation(
            session_id,
            content,
            next_offset,
            has_new_output,
            dropped_chars,
            state,
            shell_kind,
        )
        self._advance_terminal_read_cursor(session_id, next_offset, mode='delta')
        return obs

    async def terminal_input(self, action: TerminalInputAction) -> Observation:
        session = self.session_manager.get_session(action.session_id)
        if not session:
            return self._missing_terminal_session_error(
                action.session_id, operation='input'
            )

        scope_error = self._validate_interactive_session_scope(
            action.session_id, session
        )
        if scope_error is not None:
            return scope_error

        try:
            resize_err = self._apply_terminal_resize_if_requested(
                session, action.rows, action.cols
            )
            if resize_err is not None:
                return resize_err

            shell_kind = self._terminal_shell_kind(session)

            preflight_err = self._terminal_input_preflight(
                action.input, action, shell_kind
            )
            if preflight_err is not None:
                return preflight_err

            sent_input, predicted_cwd, policy_error = self._terminal_input_write(
                session, action, shell_kind
            )
            if policy_error is not None:
                return policy_error

            read_offset = self._get_terminal_read_cursor(action.session_id)
            probe_reads = await self._terminal_input_poll(
                session, sent_input, read_offset
            )

            return self._terminal_input_build_observation(
                action, session, read_offset, probe_reads, shell_kind
            )
        except Exception as exc:
            logger.error(
                'Error sending input to terminal %s: %s', action.session_id, exc
            )
            return ErrorObservation(f'Failed to send input: {exc}')

    def _terminal_input_preflight(
        self,
        write_content: str,
        action: TerminalInputAction,
        shell_kind: str,
    ) -> ErrorObservation | None:
        if write_content and not action.is_control:
            policy_line = write_content.rstrip('\r\n')
            preflight_err = self._terminal_input_preflight_error(
                policy_line,
                shell_kind=shell_kind,
            )
            if preflight_err is not None:
                preflight_err.tool_result = {
                    'tool': 'terminal_manager',
                    'ok': False,
                    'error_code': 'TERMINAL_INPUT_PREFLIGHT_REJECTED',
                    'retryable': True,
                    'state': 'SESSION_UNCHANGED',
                    'next_actions': ['input', 'read'],
                    'payload': {
                        'session_id': action.session_id,
                        'shell_kind': shell_kind,
                        'command_was_sent': False,
                    },
                    'progress': False,
                }
                return preflight_err
        return None

    def _terminal_input_write(
        self,
        session: Any,
        action: TerminalInputAction,
        shell_kind: str,
    ) -> tuple[bool, Path | None, ErrorObservation | None]:
        write_content = action.input
        predicted_cwd: Path | None = None
        sent_input = False

        if action.control is not None and str(action.control).strip() != '':
            session.write_input(str(action.control), is_control=True)
            sent_input = True

        if write_content:
            result = self._terminal_input_write_text(session, action, write_content)
            if result[2] is not None:
                return sent_input, result[1], result[2]
            predicted_cwd = result[1]
            sent_input = sent_input or result[0]

        if predicted_cwd is not None and hasattr(session, '_cwd'):
            session._cwd = str(predicted_cwd)  # type: ignore[attr-defined]

        return sent_input, predicted_cwd, None

    def _terminal_input_write_text(
        self,
        session: Any,
        action: TerminalInputAction,
        write_content: str,
    ) -> tuple[bool, Path | None, ErrorObservation | None]:
        predicted_cwd: Path | None = None
        if not action.is_control:
            policy_line = write_content.rstrip('\r\n')
            predicted_cwd, policy_error = self._evaluate_interactive_terminal_command(
                policy_line,
                Path(getattr(session, 'cwd', self._initial_cwd)).resolve(),
            )
            if policy_error is not None:
                return False, predicted_cwd, policy_error

        to_send = write_content
        if (
            action.submit
            and not action.is_control
            and to_send
            and not to_send.endswith(('\n', '\r\n'))
        ):
            to_send = f'{to_send}\n'

        session.write_input(to_send, is_control=action.is_control)
        return True, predicted_cwd, None

    async def _terminal_input_poll(
        self,
        session: Any,
        sent_input: bool,
        read_offset: int,
    ) -> int:
        probe_reads = 0
        if sent_input and self._should_poll_terminal_input_delta(session):
            poll_interval = PTY_READ_POLL_INTERVAL_SECONDS
            poll_timeout = PTY_INPUT_READ_TIMEOUT_SECONDS
            waited = 0.0
            while waited < poll_timeout:
                await asyncio.sleep(poll_interval)
                waited += poll_interval
                probe_reads += 1
                probe, *_ = self._read_terminal_with_mode(
                    session=session, mode='delta', offset=read_offset
                )
                if probe:
                    break
        return probe_reads

    def _terminal_input_build_observation(
        self,
        action: TerminalInputAction,
        session: Any,
        read_offset: int,
        probe_reads: int,
        shell_kind: str,
    ) -> Observation:
        content, next_offset, has_new_output, dropped_chars = (
            self._read_terminal_with_mode(
                session=session,
                mode='delta',
                offset=read_offset,
            )
        )
        state = self._terminal_output_state(
            content,
            default='SESSION_INTERACTED',
            shell_kind=shell_kind,
        )
        self._log_terminal_debug(
            'H6_terminal_input_probe_loop',
            'backend/execution/action_execution_server_io.py:terminal_input',
            'terminal-input-read-stats',
            {
                'session_id': action.session_id,
                'read_offset': read_offset,
                'probe_reads': probe_reads,
                'next_offset': next_offset,
                'has_new_output': has_new_output,
            },
        )
        self._advance_terminal_read_cursor(action.session_id, next_offset, mode='delta')
        self._mark_terminal_session_interaction(action.session_id)
        return self._build_terminal_observation(
            action.session_id,
            content,
            next_offset,
            has_new_output,
            dropped_chars,
            state,
            shell_kind,
        )

    async def terminal_read(self, action: TerminalReadAction) -> Observation:
        session = self.session_manager.get_session(action.session_id)
        if not session:
            return self._missing_terminal_session_error(
                action.session_id, operation='read'
            )

        scope_error = self._validate_interactive_session_scope(
            action.session_id, session
        )
        if scope_error is not None:
            return scope_error

        try:
            resize_err = self._apply_terminal_resize_if_requested(
                session, action.rows, action.cols
            )
            if resize_err is not None:
                return resize_err

            mode = self._terminal_mode(action.mode)
            read_offset = (
                action.offset
                if action.offset is not None
                else (
                    self._get_terminal_read_cursor(action.session_id)
                    if mode == 'delta'
                    else 0
                )
            )
            content, next_offset, has_new_output, dropped_chars = (
                self._read_terminal_with_mode(
                    session=session,
                    mode=mode,
                    offset=read_offset,
                )
            )
            self._advance_terminal_read_cursor(
                action.session_id, next_offset, mode=mode
            )
            self._mark_terminal_session_interaction(action.session_id)
            if has_new_output:
                _reset_terminal_empty_read_streak_impl(self, action.session_id)
            elif mode == 'delta' and TERMINAL_EMPTY_READ_CLOSE_THRESHOLD > 0:
                streak = _bump_terminal_empty_read_streak_impl(self, action.session_id)
                if streak >= TERMINAL_EMPTY_READ_CLOSE_THRESHOLD:
                    self.session_manager.close_session(action.session_id)
                    self._clear_terminal_read_cursor(action.session_id)
                    _reset_terminal_empty_read_streak_impl(self, action.session_id)
                    return ErrorObservation(
                        content=(
                            f'TERMINAL_SESSION_CLOSED: session "{action.session_id}" '
                            f'produced no new output for {streak} consecutive '
                            'terminal_read calls and was closed to prevent a ghost '
                            'session loop. Open a new terminal session or use '
                            'execute_powershell for one-shot commands.'
                        ),
                        error_id='TERMINAL_EMPTY_READ_STREAK',
                    )
            empty_hints = self._terminal_read_empty_hints(
                mode=mode, has_new_output=has_new_output
            )
            shell_kind = self._terminal_shell_kind(session)
            state = (
                'SESSION_OUTPUT_DELTA' if mode == 'delta' else 'SESSION_OUTPUT_SNAPSHOT'
            )
            state = self._terminal_output_state(
                content,
                default=state,
                shell_kind=shell_kind,
            )
            obs = TerminalObservation(
                session_id=action.session_id,
                content=content,
                next_offset=next_offset,
                has_new_output=has_new_output,
                dropped_chars=dropped_chars,
                state=state,
            )
            obs.tool_result = {
                'tool': 'terminal_manager',
                'ok': True,
                'error_code': None,
                'retryable': False,
                'state': state,
                'next_actions': ['read', 'input'],
                'payload': {
                    'session_id': action.session_id,
                    'shell_kind': shell_kind,
                    'mode': mode,
                    'request_offset': action.offset,
                    'next_offset': next_offset,
                    'has_new_output': has_new_output,
                    'dropped_chars': dropped_chars,
                    **empty_hints,
                },
                'progress': bool(has_new_output),
            }
            return obs
        except Exception as exc:
            logger.error('Error reading terminal %s: %s', action.session_id, exc)
            return ErrorObservation(f'Failed to read terminal: {exc}')

    async def terminal_close(self, action: TerminalCloseAction) -> Observation:
        """Explicitly close an interactive terminal session.

        Sessions are otherwise garbage-collected by the runtime (timeout /
        LRU), so this is an opt-in fast path: it releases the PTY and the
        read-cursor bookkeeping immediately. Closing an unknown ``session_id``
        is a no-op (idempotent) so the agent can call it speculatively
        without first probing for existence.
        """
        session_id = action.session_id
        try:
            session = self.session_manager.get_session(session_id)
            if session is None:
                self._clear_terminal_read_cursor(session_id)
                obs = Observation(
                    content=(
                        f'Terminal session {session_id!r} was not active; '
                        'close is a no-op.'
                    )
                )
                obs.tool_result = {
                    'tool': 'terminal_manager',
                    'ok': True,
                    'error_code': None,
                    'retryable': False,
                    'state': 'SESSION_NOT_FOUND',
                    'next_actions': ['open'],
                    'payload': {'session_id': session_id},
                    'progress': False,
                }
                return obs

            self.session_manager.close_session(session_id)
            self._clear_terminal_read_cursor(session_id)
            obs = Observation(
                content=f'Closed terminal session {session_id!r}.'
            )
            obs.tool_result = {
                'tool': 'terminal_manager',
                'ok': True,
                'error_code': None,
                'retryable': False,
                'state': 'SESSION_CLOSED',
                'next_actions': ['open'],
                'payload': {'session_id': session_id},
                'progress': False,
            }
            return obs
        except Exception as exc:
            logger.error(
                'Error closing terminal %s: %s', action.session_id, exc
            )
            return ErrorObservation(f'Failed to close terminal: {exc}')
