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
)
from backend.core.logger import app_logger as logger
from backend.execution.action_execution_server_helpers import (
    advance_terminal_read_cursor as _advance_terminal_read_cursor_impl,
)
from backend.execution.action_execution_server_helpers import (
    clear_terminal_read_cursor as _clear_terminal_read_cursor_impl,
)
from backend.execution.action_execution_server_helpers import (
    get_terminal_read_cursor as _get_terminal_read_cursor_impl,
)
from backend.execution.action_execution_server_helpers import (
    mark_terminal_session_interaction as _mark_terminal_session_interaction_impl,
)
from backend.execution.action_execution_server_helpers import (
    missing_terminal_session_error as _missing_terminal_session_error_impl,
)
from backend.execution.action_execution_server_helpers import (
    next_terminal_session_id as _next_terminal_session_id_impl,
)
from backend.execution.action_execution_server_helpers import (
    normalize_terminal_command as _normalize_terminal_command_impl,
)
from backend.execution.action_execution_server_helpers import (
    read_terminal_with_mode as _read_terminal_with_mode_impl,
)
from backend.execution.action_execution_server_helpers import (
    should_poll_terminal_input_delta as _should_poll_terminal_input_delta_impl,
)
from backend.execution.action_execution_server_helpers import (
    terminal_input_preflight_error as _terminal_input_preflight_error_impl,
)
from backend.execution.action_execution_server_helpers import (
    terminal_mode as _terminal_mode_impl,
)
from backend.execution.action_execution_server_helpers import (
    terminal_open_guardrail_error as _terminal_open_guardrail_error_impl,
)
from backend.execution.action_execution_server_helpers import (
    terminal_output_state as _terminal_output_state_impl,
)
from backend.execution.action_execution_server_helpers import (
    terminal_read_empty_hints as _terminal_read_empty_hints_impl,
)
from backend.execution.action_execution_server_helpers import (
    terminal_shell_kind as _terminal_shell_kind_impl,
)
from backend.execution.utils.unified_shell import BaseShellSession
from backend.ledger.action.terminal import (
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

    async def terminal_run(self, action: TerminalRunAction) -> Observation:
        try:
            guard_err = self._terminal_open_guardrail_error(action.command or '')
            if guard_err is not None:
                # #region agent log
                try:
                    payload = {
                        'sessionId': 'fee086',
                        'runId': 'pre-fix',
                        'hypothesisId': 'H7_terminal_run_branch',
                        'location': 'backend/execution/action_execution_server_io.py:terminal_run',
                        'message': 'terminal-run-guard-error',
                        'data': {'command': action.command or ''},
                        'timestamp': int(time.time() * 1000),
                    }
                    self._append_debug_trace(payload)
                except Exception:
                    pass
                # #endregion
                return guard_err

            session_id = self._next_terminal_session_id()

            default_session = self.session_manager.get_session('default')
            cwd = action.cwd
            if not cwd and default_session:
                cwd = default_session.cwd
            if not cwd:
                cwd = self._initial_cwd

            cwd_error = self._validate_workspace_scoped_cwd(
                action.command or '<interactive terminal>',
                action.cwd,
                cwd,
            )
            if cwd_error is not None:
                # #region agent log
                try:
                    payload = {
                        'sessionId': 'fee086',
                        'runId': 'pre-fix',
                        'hypothesisId': 'H7_terminal_run_branch',
                        'location': 'backend/execution/action_execution_server_io.py:terminal_run',
                        'message': 'terminal-run-cwd-error',
                        'data': {'command': action.command or '', 'cwd': cwd},
                        'timestamp': int(time.time() * 1000),
                    }
                    self._append_debug_trace(payload)
                except Exception:
                    pass
                # #endregion
                return cwd_error

            cwd = str(self._resolve_effective_cwd(action.cwd, cwd))

            session = self.session_manager.create_session(
                session_id=session_id, cwd=cwd, interactive=True
            )
            shell_kind = self._terminal_shell_kind(session)

            resize_err = self._apply_terminal_resize_if_requested(
                session, action.rows, action.cols
            )
            if resize_err is not None:
                self.session_manager.close_session(session_id)
                self._clear_terminal_read_cursor(session_id)
                # #region agent log
                try:
                    payload = {
                        'sessionId': 'fee086',
                        'runId': 'pre-fix',
                        'hypothesisId': 'H8_terminal_resize_branch',
                        'location': 'backend/execution/action_execution_server_io.py:terminal_run',
                        'message': 'terminal-run-resize-error',
                        'data': {'rows': action.rows, 'cols': action.cols},
                        'timestamp': int(time.time() * 1000),
                    }
                    self._append_debug_trace(payload)
                except Exception:
                    pass
                # #endregion
                return resize_err

            if action.command:
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

                predicted_cwd, policy_error = (
                    self._evaluate_interactive_terminal_command(
                        action.command,
                        Path(cwd).resolve(),
                    )
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
                session.write_input(action.command + '\n')
                if predicted_cwd is not None and hasattr(session, '_cwd'):
                    session._cwd = str(predicted_cwd)  # type: ignore[attr-defined]

                # Poll for initial output — the PTY shell needs processing time
                # before any bytes appear in the buffer.  Without a settle delay
                # the immediate read is always empty (particularly pronounced on
                # Windows / PowerShell where startup latency can exceed 500 ms).
                # We poll in 50 ms ticks for up to PTY_OPEN_READ_TIMEOUT_SECONDS
                # and exit as soon as any output arrives; slow commands just need
                # a follow-up read.
                _open_poll_interval = PTY_READ_POLL_INTERVAL_SECONDS
                _open_poll_timeout = PTY_OPEN_READ_TIMEOUT_SECONDS
                _open_waited = 0.0
                while _open_waited < _open_poll_timeout:
                    await asyncio.sleep(_open_poll_interval)
                    _open_waited += _open_poll_interval
                    _probe, *_ = self._read_terminal_with_mode(
                        session=session, mode='delta', offset=0
                    )
                    if _probe:
                        break

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
            obs = TerminalObservation(
                session_id=session_id,
                content=content,
                next_offset=next_offset,
                has_new_output=has_new_output,
                dropped_chars=dropped_chars,
                state=state,
            )
            empty_hints = self._terminal_read_empty_hints(
                mode='delta', has_new_output=has_new_output
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
                    'mode': 'delta',
                    'next_offset': next_offset,
                    'has_new_output': has_new_output,
                    'dropped_chars': dropped_chars,
                    **empty_hints,
                },
                'progress': bool(has_new_output),
            }
            self._advance_terminal_read_cursor(session_id, next_offset, mode='delta')
            return obs
        except Exception as exc:
            # #region agent log
            try:
                payload = {
                    'sessionId': 'fee086',
                    'runId': 'pre-fix',
                    'hypothesisId': 'H9_terminal_run_exception',
                    'location': 'backend/execution/action_execution_server_io.py:terminal_run',
                    'message': 'terminal-run-exception',
                    'data': {'error': str(exc), 'error_type': type(exc).__name__},
                    'timestamp': int(time.time() * 1000),
                }
                self._append_debug_trace(payload)
            except Exception:
                pass
            # #endregion
            logger.error('Error starting terminal session: %s', exc, exc_info=True)
            return ErrorObservation(f'Failed to start terminal: {exc}')

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
            write_content = action.input
            predicted_cwd: Path | None = None
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

            sent_input = False
            if action.control is not None and str(action.control).strip() != '':
                session.write_input(str(action.control), is_control=True)
                sent_input = True

            if write_content:
                if not action.is_control:
                    policy_line = write_content.rstrip('\r\n')
                    predicted_cwd, policy_error = (
                        self._evaluate_interactive_terminal_command(
                            policy_line,
                            Path(getattr(session, 'cwd', self._initial_cwd)).resolve(),
                        )
                    )
                    if policy_error is not None:
                        return policy_error

                to_send = write_content
                if (
                    action.submit
                    and not action.is_control
                    and to_send
                    and not to_send.endswith(('\n', '\r\n'))
                ):
                    to_send = f'{to_send}\n'

                session.write_input(to_send, is_control=action.is_control)
                sent_input = True
            if predicted_cwd is not None and hasattr(session, '_cwd'):
                session._cwd = str(predicted_cwd)  # type: ignore[attr-defined]
            # Poll for new bytes after sending input instead of a flat sleep.
            # The previous fixed 0.2 s wait was a workaround for the agent
            # racing the PTY: it returned even when the shell hadn't echoed
            # yet on slow startups (cold PowerShell, npm scripts, REPL
            # prompts), forcing the agent to either spam empty reads or rely
            # on a client-side delay. Polling in 50 ms ticks with an early
            # exit on first byte gives the shell time to flush without
            # blocking when output arrives quickly.
            _input_poll_interval = PTY_READ_POLL_INTERVAL_SECONDS
            _input_poll_timeout = PTY_INPUT_READ_TIMEOUT_SECONDS
            _input_waited = 0.0
            read_offset = self._get_terminal_read_cursor(action.session_id)
            _probe_reads = 0
            # Probe-loop only for PTY-backed sessions, where delta reads are
            # explicitly non-destructive. This closes the PowerShell/ConPTY race
            # even after the cursor has advanced, while avoiding destructive
            # polling on legacy shell backends.
            if sent_input and self._should_poll_terminal_input_delta(session):
                while _input_waited < _input_poll_timeout:
                    await asyncio.sleep(_input_poll_interval)
                    _input_waited += _input_poll_interval
                    _probe_reads += 1
                    _probe, *_ = self._read_terminal_with_mode(
                        session=session, mode='delta', offset=read_offset
                    )
                    if _probe:
                        break
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
            # #region agent log
            try:
                payload = {
                    'sessionId': 'fee086',
                    'runId': 'pre-fix',
                    'hypothesisId': 'H6_terminal_input_probe_loop',
                    'location': 'backend/execution/action_execution_server_io.py:terminal_input',
                    'message': 'terminal-input-read-stats',
                    'data': {
                        'session_id': action.session_id,
                        'read_offset': read_offset,
                        'probe_reads': _probe_reads,
                        'next_offset': next_offset,
                        'has_new_output': has_new_output,
                    },
                    'timestamp': int(time.time() * 1000),
                }
                self._append_debug_trace(payload)
            except Exception:
                pass
            # #endregion
            self._advance_terminal_read_cursor(
                action.session_id, next_offset, mode='delta'
            )
            self._mark_terminal_session_interaction(action.session_id)
            empty_hints = self._terminal_read_empty_hints(
                mode='delta', has_new_output=has_new_output
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
                    'mode': 'delta',
                    'next_offset': next_offset,
                    'has_new_output': has_new_output,
                    'dropped_chars': dropped_chars,
                    **empty_hints,
                },
                'progress': bool(has_new_output),
            }
            return obs
        except Exception as exc:
            logger.error(
                'Error sending input to terminal %s: %s', action.session_id, exc
            )
            return ErrorObservation(f'Failed to send input: {exc}')

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
