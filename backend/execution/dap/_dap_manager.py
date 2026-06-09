"""DAPDebugManager — DAP protocol implementation.

Extracted from backend/execution/debugger.py to keep the parent module
under the per-file LOC budget.
"""

from __future__ import annotations

import json
import logging
import sys
import uuid
from pathlib import Path
from typing import Any

from backend.core.logger import app_logger as logger
from backend.execution.dap._dap_adapters import (
    _language_from_extension,
    _resolve_recipe,
)
from backend.execution.dap._dap_errors import DAPError
from backend.execution.dap._dap_logging import _dap_log
from backend.execution.dap._dap_session import DAPDebugSession
from backend.ledger.action.debugger import DebuggerAction
from backend.ledger.observation import ErrorObservation
from backend.ledger.observation.debugger import DebuggerObservation
from backend.utils.language_tool_aliases import normalize_debug_adapter_name


class DAPDebugManager:
    """Manage multiple DAP debugger sessions."""

    _PYTHON_ADAPTERS = {'python', 'debugpy'}
    _EXTENSION_ADAPTERS = {
        '.py': 'python',
        '.pyw': 'python',
        '.js': 'javascript',
        '.mjs': 'javascript',
        '.cjs': 'javascript',
        '.ts': 'typescript',
        '.tsx': 'typescript',
        '.jsx': 'javascript',
        '.go': 'go',
        '.rs': 'rust',
        '.java': 'java',
        '.cs': 'csharp',
        '.cpp': 'cpp',
        '.cc': 'cpp',
        '.cxx': 'cpp',
        '.c': 'c',
    }

    def __init__(self, workspace_root: str) -> None:
        self.workspace_root = workspace_root
        self.sessions: dict[str, DAPDebugSession] = {}

    def handle(self, action: DebuggerAction) -> DebuggerObservation | ErrorObservation:
        """Dispatch a debugger action and wrap it as an observation."""
        debug_action = (action.debug_action or '').strip().lower()
        timeout = float(action.timeout or 10.0)
        start_timeout = max(timeout, 15.0)
        _dap_log(
            logging.INFO,
            f'Debugger dispatch: {debug_action or "<empty>"}',
            msg_type='DEBUGGER_DISPATCH',
            debug_action=debug_action or None,
            session_id=action.session_id,
            program=action.program,
            workspace_root=str(self.workspace_root),
            process_cwd=str(Path.cwd()),
            adapter_hint=action.adapter_id or action.language or action.adapter,
            timeout_seconds=timeout,
            effective_timeout_seconds=start_timeout
            if debug_action == 'start'
            else timeout,
        )
        try:
            if debug_action == 'start':
                payload = self._start(action, timeout=start_timeout)
            else:
                session = self._get_session(action.session_id)
                payload = self._dispatch_existing(
                    session, action, debug_action, timeout
                )
            return self._observation(debug_action, payload)
        except Exception as exc:
            return self._handle_dispatch_exception(
                exc, action, debug_action
            )

    def _drop_session(self, session: DAPDebugSession) -> None:
        self.sessions.pop(session.session_id, None)
        try:
            session.close()
        except Exception:
            logger.debug('DAP session close after dispatch error failed', exc_info=True)

    def _handle_dispatch_exception(
        self, exc: Exception, action: DebuggerAction, debug_action: str
    ) -> ErrorObservation:
        stderr_tail = self._stderr_tail_for(action)
        phase = getattr(exc, 'phase', None)
        exc_timeout: Any | None = getattr(exc, 'timeout', None)
        phase_suffix = f'\nstartup_phase: {phase}' if phase else ''
        timeout_suffix = (
            f'\nstartup_timeout_seconds: {float(exc_timeout):.1f}'
            if isinstance(exc_timeout, (int, float)) and exc_timeout > 0
            else ''
        )
        suffix = f'\nadapter_stderr:\n{stderr_tail}' if stderr_tail else ''
        logger.warning(
            'DAP: %s failed for session=%s: %s',
            debug_action or '<unknown>',
            action.session_id or '<new>',
            exc,
        )
        return ErrorObservation(
            f'Debugger error: {type(exc).__name__}: {exc}{phase_suffix}{timeout_suffix}{suffix}'
        )

    def _stderr_tail_for(self, action: DebuggerAction) -> str:
        session = self.sessions.get(action.session_id) if action.session_id else None
        if session is None:
            return ''
        try:
            tail = session.client.stderr_tail()
        except Exception:
            return ''
        if not tail:
            return ''
        return '\n'.join(line.rstrip() for line in tail)

    def close_all(self) -> None:
        """Close all active debug sessions."""
        sessions = list(self.sessions.values())
        self.sessions.clear()
        for session in sessions:
            session.close()

    def _start(self, action: DebuggerAction, timeout: float) -> dict[str, Any]:
        request = (action.request or 'launch').strip().lower()
        if request not in {'launch', 'attach'}:
            raise DAPError("debugger request must be 'launch' or 'attach'")

        session_id = action.session_id or f'dbg-{uuid.uuid4().hex[:8]}'
        if session_id in self.sessions:
            raise DAPError(f'Debug session already exists: {session_id}')

        adapter = self._adapter_name(action)
        adapter_command = self._adapter_command(action, adapter)
        _dap_log(
            logging.INFO,
            'DAP adapter command resolved',
            msg_type='DAP_ADAPTER_RESOLVED',
            dap_session_id=session_id,
            adapter=adapter,
            adapter_argv0=adapter_command[0] if adapter_command else None,
            program=action.program,
        )
        adapter_id = action.adapter_id or adapter or 'generic'
        language = action.language or adapter

        session = self._build_session(
            session_id, action, adapter_id, language, request,
            adapter_command,
        )
        self.sessions[session_id] = session
        try:
            return session.start(timeout=timeout)
        except Exception:
            self.sessions.pop(session_id, None)
            session.close()
            raise

    def _build_session(
        self,
        session_id: str,
        action: DebuggerAction,
        adapter_id: str,
        language: str,
        request: str,
        adapter_command: list[str],
    ) -> DAPDebugSession:
        return DAPDebugSession(
            session_id,
            workspace_root=self.workspace_root,
            adapter_command=adapter_command,
            adapter_id=adapter_id,
            language=language,
            request=request,
            program=action.program,
            cwd=action.cwd,
            args=[str(arg) for arg in action.args],
            breakpoints=action.breakpoints,
            stop_on_entry=bool(action.stop_on_entry),
            just_my_code=bool(action.just_my_code),
            launch_config=action.launch_config,
            initialize_options=action.initialize_options,
            python=action.python,
        )

    def _dispatch_existing(
        self,
        session: DAPDebugSession,
        action: DebuggerAction,
        debug_action: str,
        timeout: float,
    ) -> dict[str, Any]:
        try:
            handler = self._DISPATCH_TABLE[debug_action]
        except KeyError:
            raise DAPError(f'Unknown debugger action: {debug_action}')
        try:
            return handler(self, session, action, timeout)
        except Exception:
            self._drop_session(session)
            raise

    def _action_set_breakpoints(self, session: DAPDebugSession, action: DebuggerAction, timeout: float) -> dict[str, Any]:
        if not action.file:
            raise DAPError('set_breakpoints requires file')
        return session.set_breakpoints(action.file, action.lines, action.breakpoints or None, timeout=timeout)

    def _action_continue(self, session: DAPDebugSession, action: DebuggerAction, timeout: float) -> dict[str, Any]:
        return session.continue_execution(action.thread_id, timeout=timeout)

    @staticmethod
    def _action_step(step_kind: str):
        def handler(self, session: DAPDebugSession, action: DebuggerAction, timeout: float) -> dict[str, Any]:
            return session.step(step_kind, action.thread_id, timeout=timeout)
        return handler

    def _action_pause(self, session: DAPDebugSession, action: DebuggerAction, timeout: float) -> dict[str, Any]:
        return session.pause(action.thread_id, timeout=timeout)

    def _action_stack(self, session: DAPDebugSession, action: DebuggerAction, timeout: float) -> dict[str, Any]:
        return session.stack_trace(action.thread_id, timeout=timeout)

    def _action_scopes(self, session: DAPDebugSession, action: DebuggerAction, timeout: float) -> dict[str, Any]:
        if action.frame_id is None:
            raise DAPError('scopes requires frame_id')
        return session.scopes(action.frame_id, timeout=timeout)

    def _action_variables(self, session: DAPDebugSession, action: DebuggerAction, timeout: float) -> dict[str, Any]:
        if action.variables_reference is None:
            raise DAPError('variables requires variables_reference')
        return session.variables(action.variables_reference, action.count, timeout=timeout)

    def _action_evaluate(self, session: DAPDebugSession, action: DebuggerAction, timeout: float) -> dict[str, Any]:
        if not action.expression:
            raise DAPError('evaluate requires expression')
        return session.evaluate(action.expression, action.frame_id, timeout=timeout)

    def _action_status(self, session: DAPDebugSession, action: DebuggerAction, timeout: float) -> dict[str, Any]:
        return session.status(timeout=timeout)

    def _action_stop(self, session: DAPDebugSession, action: DebuggerAction, timeout: float) -> dict[str, Any]:
        payload = session.stop(timeout=timeout)
        self.sessions.pop(session.session_id, None)
        return payload

    _DISPATCH_TABLE: dict[str, Any] = {
        'set_breakpoints': _action_set_breakpoints,
        'continue': _action_continue,
        'next': _action_step('next'),
        'step_in': _action_step('stepIn'),
        'step_out': _action_step('stepOut'),
        'pause': _action_pause,
        'stack': _action_stack,
        'scopes': _action_scopes,
        'variables': _action_variables,
        'evaluate': _action_evaluate,
        'status': _action_status,
        'stop': _action_stop,
    }

    def _adapter_name(self, action: DebuggerAction) -> str | None:
        adapter = action.adapter or action.language
        if adapter:
            return normalize_debug_adapter_name(adapter)
        if action.program:
            return self._EXTENSION_ADAPTERS.get(Path(action.program).suffix.lower())
        return None

    def _adapter_command(
        self, action: DebuggerAction, adapter: str | None
    ) -> list[str]:
        if action.adapter_command:
            return action.adapter_command
        if adapter in self._PYTHON_ADAPTERS:
            return [action.python or sys.executable, '-m', 'debugpy.adapter']
        # Auto-discovery: probe PATH for a known adapter so the model
        # doesn't have to hand-roll ``adapter_command`` for the common
        # languages (Go/dlv, Rust/codelldb, JS/js-debug, C#/netcoredbg, …).
        discovered: list[str] | None = None
        if adapter:
            discovered = _resolve_recipe(adapter)
        if discovered is None and action.program:
            lang = _language_from_extension(Path(action.program).suffix)
            if lang:
                discovered = _resolve_recipe(lang)
        if discovered is not None:
            return discovered
        hint = f' for adapter {adapter!r}' if adapter else ''
        raise DAPError(
            'debugger start requires adapter_command'
            f'{hint}. No DAP adapter found on PATH; install one '
            '(e.g. dlv for Go, codelldb for Rust/C++, js-debug-adapter for '
            'Node/TS, netcoredbg for C#) or pass adapter_command explicitly.'
        )

    def _get_session(self, session_id: str | None) -> DAPDebugSession:
        if not session_id:
            raise DAPError('debugger action requires session_id')
        session = self.sessions.get(session_id)
        if session is None:
            raise DAPError(f'Debug session does not exist: {session_id}')
        return session

    @staticmethod
    def _observation(debug_action: str, payload: dict[str, Any]) -> DebuggerObservation:
        content = json.dumps(payload, indent=2, default=str)
        observation = DebuggerObservation(
            content=content,
            session_id=payload.get('session_id'),
            state=payload.get('state'),
            payload=payload,
        )
        observation.tool_result = {
            'tool': 'debugger',
            'ok': True,
            'error_code': None,
            'retryable': False,
            'state': payload.get('state'),
            'action': debug_action,
            'payload': payload,
            'progress': True,
        }
        return observation
