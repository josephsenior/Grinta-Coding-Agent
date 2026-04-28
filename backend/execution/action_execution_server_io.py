"""Mixins for RuntimeExecutor command, terminal, and file IO behaviors."""

from __future__ import annotations

import asyncio
import os
import re
import uuid
from pathlib import Path
from typing import Any, cast

from binaryornot.check import is_binary

from backend.core.enums import FileReadSource
from backend.core.logger import app_logger as logger
from backend.execution.action_execution_server_helpers import (
    annotate_environment_errors as _annotate_environment_errors_impl,
    append_blast_radius_warning as _append_blast_radius_warning_impl,
    apply_grep_filter as _apply_grep_filter_impl,
    apply_terminal_resize_if_requested as _apply_terminal_resize_if_requested_impl,
    attach_detected_server as _attach_detected_server_impl,
    build_env_check_command as _build_env_check_command_impl,
    build_shell_git_config_command as _build_shell_git_config_command_impl,
    clear_terminal_read_cursor as _clear_terminal_read_cursor_impl,
    detect_powershell_in_bash_mismatch as _detect_powershell_in_bash_mismatch_impl,
    detect_scaffold_setup_failure as _detect_scaffold_setup_failure_impl,
    edit_try_directory_view as _edit_try_directory_view_impl,
    edit_via_file_editor as _edit_via_file_editor_impl,
    evaluate_interactive_terminal_command as _evaluate_interactive_terminal_command_impl,
    extract_failure_signature as _extract_failure_signature_impl,
    get_terminal_read_cursor as _get_terminal_read_cursor_impl,
    handle_aci_file_read as _handle_aci_file_read_impl,
    init_shell_commands as _init_shell_commands_impl,
    is_auto_lint_enabled as _is_auto_lint_enabled_impl,
    is_sandboxed_local as _is_sandboxed_local_impl,
    is_workspace_restricted_profile as _is_workspace_restricted_profile_impl,
    mark_terminal_session_interaction as _mark_terminal_session_interaction_impl,
    missing_terminal_session_error as _missing_terminal_session_error_impl,
    next_terminal_session_id as _next_terminal_session_id_impl,
    normalize_terminal_command as _normalize_terminal_command_impl,
    predict_interactive_cwd_change as _predict_interactive_cwd_change_impl,
    read_terminal_with_mode as _read_terminal_with_mode_impl,
    resolve_effective_cwd as _resolve_effective_cwd_impl,
    resolve_path as _resolve_path_impl,
    resolve_workspace_file_path as _resolve_workspace_file_path_impl,
    should_rewrite_python3_to_python as _should_rewrite_python3_to_python_impl,
    strip_ansi_obs_text as _strip_ansi_obs_text_impl,
    terminal_mode as _terminal_mode_impl,
    terminal_open_guardrail_error as _terminal_open_guardrail_error_impl,
    terminal_read_empty_hints as _terminal_read_empty_hints_impl,
    uses_powershell_shell_contract as _uses_powershell_shell_contract_impl,
    validate_interactive_session_scope as _validate_interactive_session_scope_impl,
    validate_workspace_scoped_cwd as _validate_workspace_scoped_cwd_impl,
    workspace_root as _workspace_root_impl,
    advance_terminal_read_cursor as _advance_terminal_read_cursor_impl,
)
from backend.execution.file_operations import (
    ensure_directory_exists,
    handle_file_read_errors,
    read_image_file,
    read_pdf_file,
    read_text_file,
    read_video_file,
    truncate_cmd_output,
    write_file_content,
)
from backend.execution.utils.unified_shell import BaseShellSession
from backend.ledger.action import (
    CmdRunAction,
    DebuggerAction,
    FileEditAction,
    FileReadAction,
    FileWriteAction,
)
from backend.ledger.action.terminal import (
    TerminalInputAction,
    TerminalReadAction,
    TerminalRunAction,
)
from backend.ledger.observation import (
    CmdOutputObservation,
    ErrorObservation,
    FileEditObservation,
    FileReadObservation,
    FileWriteObservation,
    Observation,
)
from backend.ledger.observation.terminal import TerminalObservation
from backend.utils.async_utils import call_sync_from_async


class RuntimeExecutorIOAndTerminalMixin:
    def initialized(self) -> bool:
        """Check if action execution server has completed initialization."""
        return self._initialized

    def _init_shell_commands(self):
        _init_shell_commands_impl(self)

    def _build_shell_git_config_command(self, use_powershell: bool) -> str:
        return _build_shell_git_config_command_impl(self, use_powershell)

    @staticmethod
    def _build_env_check_command(use_powershell: bool) -> str:
        return _build_env_check_command_impl(use_powershell)

    def _uses_powershell_shell_contract(self) -> bool:
        return _uses_powershell_shell_contract_impl(self)

    async def run_action(self, action) -> Observation:
        """Execute any action through action execution server."""
        async with self.lock:
            action_type = action.action
            obs = await getattr(self, action_type)(action)

        if hasattr(obs, 'content') and isinstance(obs.content, str):
            obs.content = self._strip_ansi_obs_text(obs.content)
        if hasattr(obs, 'path') and isinstance(obs.path, str):
            obs.path = self._strip_ansi_obs_text(obs.path)
        if hasattr(obs, 'message') and isinstance(obs.message, str):
            try:
                obs.message = self._strip_ansi_obs_text(obs.message)
            except AttributeError:
                pass
        return obs

    @staticmethod
    def _strip_ansi_obs_text(text: str) -> str:
        return _strip_ansi_obs_text_impl(text)

    def _should_rewrite_python3_to_python(self) -> bool:
        return _should_rewrite_python3_to_python_impl(self)

    @staticmethod
    def _extract_failure_signature(content: str) -> str:
        return _extract_failure_signature_impl(content)

    def _workspace_root(self) -> Path:
        return _workspace_root_impl(self)

    def _is_workspace_restricted_profile(self) -> bool:
        return _is_workspace_restricted_profile_impl(self)

    def _is_sandboxed_local(self) -> bool:
        return _is_sandboxed_local_impl(self)

    def _validate_interactive_session_scope(
        self, session_id: str, session: Any
    ) -> ErrorObservation | None:
        return _validate_interactive_session_scope_impl(self, session_id, session)

    def _predict_interactive_cwd_change(
        self, command: str, current_cwd: Path
    ) -> tuple[Path | None, str | None]:
        return _predict_interactive_cwd_change_impl(self, command, current_cwd)

    def _evaluate_interactive_terminal_command(
        self, command: str, current_cwd: Path
    ) -> tuple[Path | None, ErrorObservation | None]:
        return _evaluate_interactive_terminal_command_impl(self, command, current_cwd)

    def _resolve_effective_cwd(
        self, requested_cwd: str | None, base_cwd: str | None = None
    ) -> Path:
        return _resolve_effective_cwd_impl(self, requested_cwd, base_cwd)

    def _validate_workspace_scoped_cwd(
        self,
        command: str,
        requested_cwd: str | None,
        base_cwd: str | None = None,
    ) -> ErrorObservation | None:
        return _validate_workspace_scoped_cwd_impl(
            self, command, requested_cwd, base_cwd
        )

    def _resolve_workspace_file_path(self, path: str, working_dir: str) -> str:
        return _resolve_workspace_file_path_impl(self, path, working_dir)

    def _annotate_environment_errors(self, observation: CmdOutputObservation) -> None:
        _annotate_environment_errors_impl(self, observation)

    @staticmethod
    def _detect_powershell_in_bash_mismatch(command: str, content: str) -> str | None:
        return _detect_powershell_in_bash_mismatch_impl(command, content)

    @staticmethod
    def _detect_scaffold_setup_failure(command: str, content: str) -> str | None:
        return _detect_scaffold_setup_failure_impl(command, content)

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
        except Exception as exc:
            logger.error('Error running command: %s', exc)
            return ErrorObservation(str(exc))

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
        return self.debug_manager.handle(action)

    async def _run_foreground_cmd(
        self, action: CmdRunAction
    ) -> CmdOutputObservation | ErrorObservation:
        if action.is_static:
            return await self._run_static_cmd(action)
        try:
            self.session_manager.cleanup_idle_sessions(max_idle_seconds=3600)
        except Exception:
            logger.debug('cleanup_idle_sessions failed', exc_info=True)
        bash_session = self.session_manager.get_session('default')
        if bash_session is None:
            return ErrorObservation('Default shell session not initialized')
        if not isinstance(bash_session, BaseShellSession):
            return ErrorObservation('Default shell session is not a foreground shell')

        try:
            from backend.execution.utils.blocking_heuristics import (
                is_known_slow_command,
            )

            if not getattr(action, 'blocking', False) and is_known_slow_command(
                getattr(action, 'command', '') or ''
            ):
                action.blocking = True  # type: ignore[attr-defined]
                logger.info(
                    'Auto-promoted blocking=True for slow command: %s',
                    (action.command or '').splitlines()[0][:120],
                )
        except Exception:
            logger.debug('blocking-heuristic check failed', exc_info=True)

        bg_id = f'bg-{uuid.uuid4().hex[:8]}'
        if hasattr(bash_session, '_pending_bg_id'):
            bash_session._pending_bg_id = bg_id  # type: ignore[union-attr]

        observation = cast(
            CmdOutputObservation,
            await call_sync_from_async(bash_session.execute, action),
        )

        detached_pane = getattr(bash_session, '_detached_pane', None)
        detached_window = getattr(bash_session, '_detached_window', None)
        registered_bg_id = getattr(bash_session, '_bg_session_id', None)
        if (
            detached_pane is not None
            and detached_window is not None
            and registered_bg_id is not None
        ):
            from backend.execution.utils.bash import BackgroundPaneSession

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

        bg_process = getattr(bash_session, '_bg_process', None)
        bg_sub_id = getattr(bash_session, '_bg_session_id', None) or registered_bg_id
        bg_stdout_cap = getattr(bash_session, '_bg_stdout_capture', None)
        if (
            bg_process is not None
            and bg_sub_id is not None
            and bg_stdout_cap is not None
            and detached_pane is None
        ):
            from backend.execution.utils.subprocess_background import (
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

        if hasattr(bash_session, '_pending_bg_id'):
            bash_session._pending_bg_id = None  # type: ignore[union-attr]

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
        return _terminal_read_empty_hints_impl(
            mode=mode, has_new_output=has_new_output
        )

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
        _advance_terminal_read_cursor_impl(
            self, session_id, next_offset, mode=mode
        )

    def _clear_terminal_read_cursor(self, session_id: str) -> None:
        _clear_terminal_read_cursor_impl(self, session_id)

    async def terminal_run(self, action: TerminalRunAction) -> Observation:
        try:
            guard_err = self._terminal_open_guardrail_error(action.command or '')
            if guard_err is not None:
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
                return cwd_error

            cwd = str(self._resolve_effective_cwd(action.cwd, cwd))

            session = self.session_manager.create_session(
                session_id=session_id, cwd=cwd, interactive=True
            )

            resize_err = self._apply_terminal_resize_if_requested(
                session, action.rows, action.cols
            )
            if resize_err is not None:
                self.session_manager.close_session(session_id)
                self._clear_terminal_read_cursor(session_id)
                return resize_err

            if action.command:
                predicted_cwd, policy_error = self._evaluate_interactive_terminal_command(
                    action.command,
                    Path(cwd).resolve(),
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

            content, next_offset, has_new_output, dropped_chars = self._read_terminal_with_mode(
                session=session,
                mode='delta',
                offset=0,
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
                state='SESSION_OPENED',
            )
            empty_hints = self._terminal_read_empty_hints(
                mode='delta', has_new_output=has_new_output
            )
            obs.tool_result = {
                'tool': 'terminal_manager',
                'ok': True,
                'error_code': None,
                'retryable': False,
                'state': 'SESSION_OPENED',
                'next_actions': ['read', 'input'],
                'payload': {
                    'session_id': session_id,
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

            if action.control is not None and str(action.control).strip() != '':
                session.write_input(str(action.control), is_control=True)

            write_content = action.input
            predicted_cwd: Path | None = None
            if write_content:
                if not action.is_control:
                    policy_line = write_content.rstrip('\r\n')
                    predicted_cwd, policy_error = self._evaluate_interactive_terminal_command(
                        policy_line,
                        Path(getattr(session, 'cwd', self._initial_cwd)).resolve(),
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
            if predicted_cwd is not None and hasattr(session, '_cwd'):
                session._cwd = str(predicted_cwd)  # type: ignore[attr-defined]
            await asyncio.sleep(0.2)
            read_offset = self._get_terminal_read_cursor(action.session_id)
            content, next_offset, has_new_output, dropped_chars = self._read_terminal_with_mode(
                session=session,
                mode='delta',
                offset=read_offset,
            )
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
                state='SESSION_INTERACTED',
            )
            obs.tool_result = {
                'tool': 'terminal_manager',
                'ok': True,
                'error_code': None,
                'retryable': False,
                'state': 'SESSION_INTERACTED',
                'next_actions': ['read', 'input'],
                'payload': {
                    'session_id': action.session_id,
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
            logger.error('Error sending input to terminal %s: %s', action.session_id, exc)
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
            content, next_offset, has_new_output, dropped_chars = self._read_terminal_with_mode(
                session=session,
                mode=mode,
                offset=read_offset,
            )
            self._advance_terminal_read_cursor(
                action.session_id, next_offset, mode=mode
            )
            self._mark_terminal_session_interaction(action.session_id)
            empty_hints = self._terminal_read_empty_hints(
                mode=mode, has_new_output=has_new_output
            )
            state = 'SESSION_OUTPUT_DELTA' if mode == 'delta' else 'SESSION_OUTPUT_SNAPSHOT'
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

    def _resolve_path(self, path: str, working_dir: str) -> str:
        return _resolve_path_impl(self, path, working_dir)

    def _handle_aci_file_read(self, action: FileReadAction) -> FileReadObservation:
        return _handle_aci_file_read_impl(self, action)

    async def read(self, action: FileReadAction) -> Observation:
        bash_session = self.session_manager.get_session('default')
        if bash_session is None:
            return ErrorObservation('Default shell session not initialized')

        if os.path.isfile(action.path) and is_binary(action.path):
            return ErrorObservation('ERROR_BINARY_FILE')

        if action.impl_source == FileReadSource.FILE_EDITOR:
            return self._handle_aci_file_read(action)

        working_dir = bash_session.cwd
        try:
            filepath = self._resolve_workspace_file_path(action.path, working_dir)
        except PermissionError:
            return ErrorObservation(
                f"You're not allowed to access this path: {action.path}. You can only access paths inside the workspace."
            )

        try:
            if filepath.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.gif')):
                return read_image_file(filepath)
            if filepath.lower().endswith('.pdf'):
                return read_pdf_file(filepath)
            if filepath.lower().endswith(('.mp4', '.webm', '.ogg')):
                return read_video_file(filepath)
            return read_text_file(filepath, action)
        except Exception:
            return handle_file_read_errors(filepath, working_dir)

    async def write(self, action: FileWriteAction) -> Observation:
        bash_session = self.session_manager.get_session('default')
        if bash_session is None:
            return ErrorObservation('Default shell session not initialized')

        working_dir = bash_session.cwd
        try:
            filepath = self._resolve_workspace_file_path(action.path, working_dir)
        except PermissionError as exc:
            return ErrorObservation(f'Permission error on {action.path}: {exc}')

        try:
            ensure_directory_exists(filepath)
            file_exists = os.path.exists(filepath)
            error_obs = write_file_content(filepath, action, file_exists)
            if error_obs:
                return error_obs
            return FileWriteObservation(
                content=f'Wrote file: {action.path}',
                path=action.path,
            )
        except Exception as exc:
            logger.error('Error writing file %s: %s', action.path, exc, exc_info=True)
            return ErrorObservation(f'Failed to write file {action.path}: {exc}')

    def _edit_try_directory_view(
        self, filepath: str, path_for_obs: str, action: FileEditAction
    ) -> Observation | None:
        return _edit_try_directory_view_impl(self, filepath, path_for_obs, action)

    def _edit_via_file_editor(self, action: FileEditAction) -> Observation:
        return _edit_via_file_editor_impl(self, action)

    def _append_blast_radius_warning(
        self,
        base_content: str,
        *,
        command: str,
        action_path: str,
        new_content: str | None,
    ) -> str:
        return _append_blast_radius_warning_impl(
            self,
            base_content,
            command=command,
            action_path=action_path,
            new_content=new_content,
        )

    def _is_auto_lint_enabled(self) -> bool:
        return _is_auto_lint_enabled_impl(self)

    async def edit(self, action: FileEditAction) -> Observation:
        bash_session = self.session_manager.get_session('default')
        if bash_session is None:
            return ErrorObservation('Default shell session not initialized')
        working_dir = bash_session.cwd
        try:
            filepath = self._resolve_workspace_file_path(action.path, working_dir)
        except PermissionError:
            return ErrorObservation(
                f"You're not allowed to access this path: {action.path}. You can only access paths inside the workspace."
            )

        dir_view = self._edit_try_directory_view(filepath, action.path, action)
        if dir_view is not None:
            return dir_view

        if not action.command:
            return ErrorObservation(
                'Legacy edit_file actions are no longer supported. Use text_editor or symbol_editor instead.'
            )

        return self._edit_via_file_editor(action)