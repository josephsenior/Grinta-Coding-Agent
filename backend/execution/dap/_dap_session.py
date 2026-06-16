"""DAPDebugSession — DAP protocol implementation.

Extracted from backend/execution/debugger.py to keep the parent module
under the per-file LOC budget.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from backend.core.logger import app_logger as logger
from backend.execution.dap._dap_client import DAPClient
from backend.execution.dap._dap_errors import DAPError, DAPStartPhaseError
from backend.execution.dap._dap_logging import _dap_log


class DAPDebugSession:
    """Stateful DAP session controlled through standard DAP requests."""

    def __init__(
        self,
        session_id: str,
        *,
        workspace_root: str,
        adapter_command: list[str],
        adapter_transport: str,
        adapter_host: str | None,
        adapter_port: int | None,
        adapter_id: str,
        language: str | None,
        request: str,
        program: str | None,
        cwd: str | None,
        args: list[str],
        breakpoints: list[dict[str, Any]],
        stop_on_entry: bool,
        just_my_code: bool,
        launch_config: dict[str, Any],
        initialize_options: dict[str, Any],
        python: str | None,
    ) -> None:
        self.session_id = session_id
        self.workspace_root = Path(workspace_root).resolve()
        self.adapter_command = adapter_command
        self.adapter_transport = adapter_transport
        self.adapter_host = adapter_host
        self.adapter_port = adapter_port
        self.adapter_id = adapter_id
        self.language = language
        self.request = request
        self.program = self._resolve_optional_path(program)
        self.cwd = self._resolve_cwd(cwd)
        self.args = args
        self.breakpoints_by_file: dict[str, list[dict[str, Any]]] = {}
        self.stop_on_entry = stop_on_entry
        self.just_my_code = just_my_code
        self.launch_config = launch_config
        self.initialize_options = initialize_options
        self.python = python
        self.client = DAPClient(
            adapter_command,
            cwd=self.cwd or str(self.workspace_root),
            transport=adapter_transport,
            host=adapter_host,
            port=adapter_port,
        )
        self.current_thread_id: int | None = None
        self.debuggee_process_ids: set[int] = set()
        self.start_request_seq: int | None = None
        self._set_initial_breakpoints(breakpoints)

    def start(self, timeout: float = 15.0) -> dict[str, Any]:
        """Start the adapter, send launch/attach, and configure breakpoints.

        ``timeout`` is a **wall-clock budget for the entire startup sequence**
        (initialize, launch/attach, breakpoints, configurationDone). Individual
        DAP calls use the remaining slice so a large value cannot be spent
        independently on every phase (which previously allowed one stuck phase
        to burn the full budget and race the pending-action watchdog).
        """
        session_started = time.monotonic()
        wall_budget = max(float(timeout), 15.0)
        deadline = session_started + wall_budget

        def time_left() -> float:
            return max(0.05, deadline - time.monotonic())

        phase = 'spawn adapter'
        target = str(self.program) if self.program is not None else None
        _dap_log(
            logging.INFO,
            'DAP session start entering',
            msg_type='DAP_START_PHASE',
            dap_phase='enter',
            dap_session_id=self.session_id,
            wall_budget_seconds=wall_budget,
            launch_request=self.request,
            program=target,
            adapter_argv0=(self.adapter_command[0] if self.adapter_command else None),
            adapter_transport=self.adapter_transport,
            adapter_host=self.adapter_host,
            adapter_port=self.adapter_port,
            adapter_id=self.adapter_id,
            cwd=self.client.cwd,
        )
        try:
            self._start_spawn_adapter(session_started, target)
            phase = 'initialize request'
            self._start_initialize(time_left, wall_budget, session_started)
            phase = f'{self.request} request'
            self.start_request_seq = self.client.request_nowait(
                self.request, self._start_arguments()
            )
            _dap_log(
                logging.INFO,
                'DAP launch/attach request sent',
                msg_type='DAP_START_PHASE',
                dap_phase='launch_attach_sent',
                dap_session_id=self.session_id,
                start_request_seq=self.start_request_seq,
                elapsed_seconds=round(time.monotonic() - session_started, 3),
            )
            phase = 'initialized event'
            self._start_wait_initialized(time_left, wall_budget, session_started)
            phase = 'set breakpoints'
            breakpoint_results = self._sync_all_breakpoints(time_left)
            phase = 'configurationDone request'
            self._start_configuration_done(
                time_left, wall_budget, session_started, breakpoint_results
            )
            event = self._wait_for_pause_or_exit(timeout=min(0.5, time_left()))
            elapsed_total = time.monotonic() - session_started
            _dap_log(
                logging.INFO,
                'DAP session started successfully',
                msg_type='DAP_START_COMPLETE',
                dap_session_id=self.session_id,
                elapsed_seconds=round(elapsed_total, 3),
                wall_budget_seconds=wall_budget,
                program=target,
                adapter_argv0=(
                    self.adapter_command[0] if self.adapter_command else None
                ),
                adapter_transport=self.adapter_transport,
            )
            return self._snapshot(
                state='started',
                extra={'breakpoints': breakpoint_results, 'event': event},
            )
        except DAPStartPhaseError as exc:
            self._start_log_failed(phase, exc, target, wall_budget)
            try:
                self.client.close()
            except Exception:
                logger.debug(
                    'DAP client close after start-phase failure', exc_info=True
                )
            raise
        except Exception as exc:
            self._start_log_failed_unexpected(phase, exc, target, wall_budget)
            try:
                self.client.close()
            except Exception:
                logger.debug('DAP client close after startup failure', exc_info=True)
            raise DAPStartPhaseError(phase, str(exc), timeout=wall_budget) from exc

    def _start_spawn_adapter(self, session_started: float, target: str | None) -> None:
        self.client.start()
        proc = self.client.process
        _dap_log(
            logging.INFO,
            'DAP adapter subprocess spawned',
            msg_type='DAP_START_PHASE',
            dap_phase='adapter_spawned',
            dap_session_id=self.session_id,
            adapter_pid=getattr(proc, 'pid', None) if proc else None,
            process_poll=proc.poll() if proc is not None else None,
            adapter_transport=self.adapter_transport,
            elapsed_seconds=round(time.monotonic() - session_started, 3),
        )
        _dap_log(
            logging.INFO,
            'sending DAP initialize',
            msg_type='DAP_START_PHASE',
            dap_phase='initialize_send',
            dap_session_id=self.session_id,
        )

    def _start_initialize(
        self, time_left: Callable[[], float], wall_budget: float, session_started: float
    ) -> None:
        try:
            self.client.request(
                'initialize', self._initialize_arguments(), timeout=time_left()
            )
        except DAPError as exc:
            raise DAPStartPhaseError(
                'initialize request', str(exc), timeout=wall_budget
            ) from exc
        _dap_log(
            logging.INFO,
            'DAP initialize acknowledged',
            msg_type='DAP_START_PHASE',
            dap_phase='initialize_ok',
            dap_session_id=self.session_id,
            elapsed_seconds=round(time.monotonic() - session_started, 3),
        )

    def _start_wait_initialized(
        self, time_left: Callable[[], float], wall_budget: float, session_started: float
    ) -> None:
        initialized = self.client.wait_for_event('initialized', timeout=time_left())
        if initialized is None:
            raise DAPStartPhaseError(
                'initialized event',
                'DAP adapter did not send initialized event',
                timeout=wall_budget,
            )
        _dap_log(
            logging.INFO,
            'DAP initialized event received',
            msg_type='DAP_START_PHASE',
            dap_phase='initialized_event',
            dap_session_id=self.session_id,
            elapsed_seconds=round(time.monotonic() - session_started, 3),
        )

    def _start_configuration_done(
        self,
        time_left: Callable[[], float],
        wall_budget: float,
        session_started: float,
        breakpoint_results: dict[str, Any],
    ) -> None:
        try:
            self.client.request('configurationDone', {}, timeout=time_left())
        except DAPError as exc:
            raise DAPStartPhaseError(
                'configurationDone request', str(exc), timeout=wall_budget
            ) from exc
        _dap_log(
            logging.INFO,
            'configurationDone acknowledged',
            msg_type='DAP_START_PHASE',
            dap_phase='configuration_done_ok',
            dap_session_id=self.session_id,
            breakpoint_entries_count=sum(
                len(v) for v in self.breakpoints_by_file.values()
            ),
            elapsed_seconds=round(time.monotonic() - session_started, 3),
        )
        if self.start_request_seq is not None:
            try:
                self.client.wait_for_response(
                    self.start_request_seq, timeout=min(1.0, time_left())
                )
            except DAPError:
                logger.debug('DAP start response was not available yet', exc_info=True)

    def _start_log_failed(
        self,
        phase: str,
        exc: DAPStartPhaseError,
        target: str | None,
        wall_budget: float,
    ) -> None:
        _dap_log(
            logging.WARNING,
            'DAP session start failed',
            msg_type='DAP_START_FAILED',
            dap_session_id=self.session_id,
            failure_phase=getattr(exc, 'phase', phase),
            detail=str(exc),
            stderr_tail=self.client.stderr_tail(12),
            program=target,
            adapter_argv0=(self.adapter_command[0] if self.adapter_command else None),
        )

    def _start_log_failed_unexpected(
        self, phase: str, exc: Exception, target: str | None, wall_budget: float
    ) -> None:
        _dap_log(
            logging.WARNING,
            'DAP session start failed (unexpected)',
            msg_type='DAP_START_FAILED',
            dap_session_id=self.session_id,
            failure_phase=phase,
            exception_type=type(exc).__name__,
            detail=str(exc),
            stderr_tail=self.client.stderr_tail(12),
            program=target,
            adapter_argv0=(self.adapter_command[0] if self.adapter_command else None),
        )

    def set_breakpoints(
        self,
        file: str,
        lines: list[int],
        breakpoints: list[dict[str, Any]] | None = None,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        """Set breakpoints for a source file."""
        source_path = str(self._resolve_path(file))
        entries = breakpoints or [{'line': line} for line in lines]
        self.breakpoints_by_file[source_path] = [
            self._normalize_breakpoint(entry) for entry in entries
        ]
        response = self.client.request(
            'setBreakpoints',
            {
                'source': {'path': source_path},
                'breakpoints': self.breakpoints_by_file[source_path],
                'sourceModified': False,
            },
            timeout=timeout,
        )
        return self._snapshot(
            state='breakpoints_set',
            extra={'breakpoints': response.get('body', {}).get('breakpoints', [])},
        )

    def continue_execution(
        self, thread_id: int | None = None, timeout: float = 10.0
    ) -> dict[str, Any]:
        """Resume execution for a stopped thread."""
        effective_thread = self._resolve_thread_id(thread_id, timeout=timeout)
        response = self.client.request(
            'continue', {'threadId': effective_thread}, timeout=timeout
        )
        event = self._wait_for_pause_or_exit(timeout=0.75)
        return self._snapshot(
            state='continued',
            extra={'response': response.get('body', {}), 'event': event},
        )

    def step(
        self, command: str, thread_id: int | None = None, timeout: float = 10.0
    ) -> dict[str, Any]:
        """Run a stepping command: next, stepIn, or stepOut."""
        effective_thread = self._resolve_thread_id(thread_id, timeout=timeout)
        self.client.request(command, {'threadId': effective_thread}, timeout=timeout)
        event = self.client.wait_for_event('stopped', timeout=timeout)
        if event is not None:
            self._remember_thread(event)
        return self._snapshot(state=command, extra={'event': event})

    def pause(
        self, thread_id: int | None = None, timeout: float = 10.0
    ) -> dict[str, Any]:
        """Pause a running thread."""
        effective_thread = self._resolve_thread_id(thread_id, timeout=timeout)
        self.client.request('pause', {'threadId': effective_thread}, timeout=timeout)
        event = self.client.wait_for_event('stopped', timeout=timeout)
        if event is not None:
            self._remember_thread(event)
        return self._snapshot(state='paused', extra={'event': event})

    def stack_trace(
        self, thread_id: int | None = None, timeout: float = 10.0
    ) -> dict[str, Any]:
        """Return stack frames for a thread."""
        effective_thread = self._resolve_thread_id(thread_id, timeout=timeout)
        response = self.client.request(
            'stackTrace', {'threadId': effective_thread}, timeout=timeout
        )
        return self._snapshot(state='stack', extra=response.get('body', {}))

    def scopes(self, frame_id: int, timeout: float = 10.0) -> dict[str, Any]:
        """Return scopes for a stack frame."""
        response = self.client.request('scopes', {'frameId': frame_id}, timeout=timeout)
        return self._snapshot(state='scopes', extra=response.get('body', {}))

    def variables(
        self,
        variables_reference: int,
        count: int | None = None,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        """Return variables for a DAP variablesReference."""
        arguments: dict[str, Any] = {'variablesReference': variables_reference}
        if count is not None:
            arguments['count'] = count
        response = self.client.request('variables', arguments, timeout=timeout)
        return self._snapshot(state='variables', extra=response.get('body', {}))

    def evaluate(
        self,
        expression: str,
        frame_id: int | None = None,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        """Evaluate an expression in the selected frame when provided."""
        arguments: dict[str, Any] = {'expression': expression, 'context': 'watch'}
        if frame_id is not None:
            arguments['frameId'] = frame_id
        response = self.client.request('evaluate', arguments, timeout=timeout)
        return self._snapshot(state='evaluated', extra=response.get('body', {}))

    def status(self, timeout: float = 5.0) -> dict[str, Any]:
        """Return current thread and event state."""
        try:
            response = self.client.request('threads', {}, timeout=timeout)
            threads = response.get('body', {}).get('threads', [])
        except DAPError:
            threads = []
        return self._snapshot(state='status', extra={'threads': threads})

    def stop(self, timeout: float = 5.0) -> dict[str, Any]:
        """Terminate the debuggee and close the adapter."""
        try:
            self.client.request(
                'disconnect', {'terminateDebuggee': True}, timeout=timeout
            )
            self.client.wait_for_event('terminated', timeout=min(timeout, 2.0))
            self.client.wait_for_event('exited', timeout=0.5)
        except DAPError:
            logger.debug('DAP disconnect failed', exc_info=True)
        finally:
            self._terminate_debuggee_processes()
            self.client.close()
        return {
            'session_id': self.session_id,
            'state': 'stopped',
            'adapter': self.adapter_id,
            'language': self.language,
        }

    def close(self) -> None:
        """Close the session without raising."""
        try:
            self.stop(timeout=1.0)
        except Exception:
            self.client.close()

    def _initialize_arguments(self) -> dict[str, Any]:
        arguments: dict[str, Any] = {
            'adapterID': self.adapter_id,
            'clientID': 'grinta',
            'clientName': 'Grinta',
            'pathFormat': 'path',
            'linesStartAt1': True,
            'columnsStartAt1': True,
            'supportsVariableType': True,
            'supportsVariablePaging': True,
            'supportsRunInTerminalRequest': False,
        }
        if self.initialize_options:
            arguments['initializationOptions'] = self.initialize_options
        return arguments

    def _start_arguments(self) -> dict[str, Any]:
        arguments = dict(self.launch_config)
        if self.program is not None:
            arguments.setdefault('program', str(self.program))
        if self.cwd is not None:
            arguments.setdefault('cwd', self.cwd)
        if self.args:
            arguments.setdefault('args', self.args)
        if self.stop_on_entry:
            arguments.setdefault('stopOnEntry', True)
        if self._uses_python_defaults():
            if self.request == 'launch':
                arguments.setdefault('console', 'internalConsole')
            arguments.setdefault('justMyCode', self.just_my_code)
            if self.python:
                arguments.setdefault('python', self.python)
        return arguments

    def _uses_python_defaults(self) -> bool:
        adapter = self.adapter_id.lower()
        language = (self.language or '').lower()
        return adapter in {'python', 'debugpy'} or language == 'python'

    def _set_initial_breakpoints(self, breakpoints: list[dict[str, Any]]) -> None:
        for entry in breakpoints:
            file = entry.get('file') or entry.get('path') or entry.get('source')
            if not file:
                continue
            source_path = str(self._resolve_path(str(file)))
            self.breakpoints_by_file.setdefault(source_path, []).append(
                self._normalize_breakpoint(entry)
            )

    def _sync_all_breakpoints(self, time_left: Callable[[], float]) -> dict[str, Any]:
        results: dict[str, Any] = {}
        for source_path, breakpoints in self.breakpoints_by_file.items():
            response = self.client.request(
                'setBreakpoints',
                {
                    'source': {'path': source_path},
                    'breakpoints': breakpoints,
                    'sourceModified': False,
                },
                timeout=time_left(),
            )
            results[source_path] = response.get('body', {}).get('breakpoints', [])
        return results

    def _normalize_breakpoint(self, entry: dict[str, Any]) -> dict[str, Any]:
        line_value = entry.get('line')
        if line_value is None:
            raise DAPError('Breakpoint entry requires line')
        breakpoint: dict[str, Any] = {'line': int(line_value)}
        if entry.get('column'):
            breakpoint['column'] = int(entry['column'])
        if entry.get('condition'):
            breakpoint['condition'] = str(entry['condition'])
        if entry.get('hit_condition'):
            breakpoint['hitCondition'] = str(entry['hit_condition'])
        if entry.get('hitCondition'):
            breakpoint['hitCondition'] = str(entry['hitCondition'])
        if entry.get('log_message'):
            breakpoint['logMessage'] = str(entry['log_message'])
        if entry.get('logMessage'):
            breakpoint['logMessage'] = str(entry['logMessage'])
        return breakpoint

    def _resolve_optional_path(self, path: str | None) -> Path | None:
        if not path:
            return None
        return self._resolve_path(path)

    def _resolve_path(self, path: str) -> Path:
        resolved = Path(path)
        if not resolved.is_absolute():
            resolved = self.workspace_root / resolved
        return resolved.resolve()

    def _resolve_cwd(self, cwd: str | None) -> str | None:
        if cwd:
            return str(self._resolve_path(cwd))
        if self.program is not None:
            return str(self.program.parent)
        return None

    def _resolve_thread_id(self, thread_id: int | None, timeout: float) -> int:
        if thread_id is not None:
            return int(thread_id)
        if self.current_thread_id is not None:
            return self.current_thread_id
        response = self.client.request('threads', {}, timeout=timeout)
        threads = response.get('body', {}).get('threads', [])
        if not threads:
            raise DAPError('No debug thread is available')
        self.current_thread_id = int(threads[0]['id'])
        return self.current_thread_id

    def _wait_for_pause_or_exit(self, timeout: float) -> dict[str, Any] | None:
        event = self.client.wait_for_event('stopped', timeout=timeout)
        if event is None:
            event = self.client.wait_for_event('terminated', timeout=0.05)
        if event is None:
            event = self.client.wait_for_event('exited', timeout=0.05)
        if event is not None:
            self._remember_event(event)
        return event

    def _remember_event(self, event: dict[str, Any]) -> None:
        self._remember_thread(event)
        self._remember_process(event)

    def _remember_thread(self, event: dict[str, Any]) -> None:
        thread_id = event.get('body', {}).get('threadId')
        if thread_id is not None:
            self.current_thread_id = int(thread_id)

    def _remember_process(self, event: dict[str, Any]) -> None:
        if event.get('event') != 'process':
            return
        process_id = event.get('body', {}).get('systemProcessId')
        if process_id is None:
            return
        try:
            pid = int(process_id)
        except (TypeError, ValueError):
            return
        if pid > 0 and pid != os.getpid():
            self.debuggee_process_ids.add(pid)

    def _terminate_debuggee_processes(self) -> None:
        if not self.debuggee_process_ids:
            return
        try:
            import psutil

            for process_id in list(self.debuggee_process_ids):
                try:
                    process = psutil.Process(process_id)
                except psutil.NoSuchProcess:
                    continue
                processes = process.children(recursive=True) + [process]
                for candidate in processes:
                    try:
                        candidate.terminate()
                    except psutil.NoSuchProcess:
                        pass
                _, alive = psutil.wait_procs(processes, timeout=2)
                for candidate in alive:
                    try:
                        candidate.kill()
                    except psutil.NoSuchProcess:
                        pass
        except Exception:
            logger.debug('Failed to clean up DAP debuggee process tree', exc_info=True)
        finally:
            self.debuggee_process_ids.clear()

    def _target(self) -> str | None:
        if self.program is not None:
            return str(self.program)
        for key in ('program', 'processId', 'processIdString'):
            value = self.launch_config.get(key)
            if value is not None:
                return str(value)
        return None

    def _snapshot(
        self, state: str, extra: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        events = self.client.drain_events()
        for event in events:
            self._remember_event(event)
        return {
            'session_id': self.session_id,
            'state': state,
            'adapter': self.adapter_id,
            'language': self.language,
            'request': self.request,
            'target': self._target(),
            'cwd': self.cwd,
            'current_thread_id': self.current_thread_id,
            'events': events,
            'adapter_stderr': self.client.stderr_tail(),
            **(extra or {}),
        }
