"""Debug Adapter Protocol client and session manager."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from backend.core.logger import app_logger as logger
from backend.ledger.action.debugger import DebuggerAction
from backend.ledger.observation import ErrorObservation
from backend.ledger.observation.debugger import DebuggerObservation


class DAPError(RuntimeError):
    """Raised when DAP communication fails."""


class DAPClient:
    """Minimal DAP client that talks to a debug adapter over stdio."""

    def __init__(self, adapter_command: list[str], cwd: str | None = None) -> None:
        self.adapter_command = adapter_command
        self.cwd = cwd
        self.process: subprocess.Popen[bytes] | None = None
        self._seq = 0
        self._pending: dict[int, queue.Queue[dict[str, Any]]] = {}
        self._events: list[dict[str, Any]] = []
        self._stderr: list[str] = []
        self._lock = threading.RLock()
        self._event_condition = threading.Condition(self._lock)
        self._reader: threading.Thread | None = None
        self._stderr_reader: threading.Thread | None = None
        self._closed = False

    def start(self) -> None:
        """Start the adapter subprocess and reader threads."""
        if self.process is not None:
            return
        if not self.adapter_command:
            raise DAPError('DAP adapter command is empty')
        self.process = subprocess.Popen(
            self.adapter_command,
            cwd=self.cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._reader = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader.start()
        self._stderr_reader = threading.Thread(target=self._stderr_loop, daemon=True)
        self._stderr_reader.start()

    def close(self) -> None:
        """Terminate the adapter subprocess."""
        self._closed = True
        process = self.process
        if process is None:
            return
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
        finally:
            self.process = None
            # Wake any waiters and best-effort join the reader threads. They are
            # daemon=True so the process can still exit if a reader is wedged in
            # a blocking read after the subprocess pipes close, but joining here
            # avoids leaving stale handles on Windows where pipe teardown is
            # asynchronous.
            with self._lock:
                self._event_condition.notify_all()
            for reader in (self._reader, self._stderr_reader):
                if reader is not None and reader.is_alive():
                    try:
                        reader.join(timeout=1.0)
                    except Exception:
                        pass
            self._reader = None
            self._stderr_reader = None

    def request(
        self,
        command: str,
        arguments: dict[str, Any] | None = None,
        *,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        """Send a DAP request and wait for its response."""
        request_seq = self.request_nowait(command, arguments)
        return self.wait_for_response(request_seq, timeout=timeout)

    def request_nowait(
        self, command: str, arguments: dict[str, Any] | None = None
    ) -> int:
        """Send a DAP request and return its sequence number."""
        with self._lock:
            self._seq += 1
            request_seq = self._seq
            self._pending[request_seq] = queue.Queue(maxsize=1)
        self._send(
            {
                'seq': request_seq,
                'type': 'request',
                'command': command,
                'arguments': arguments or {},
            }
        )
        return request_seq

    def wait_for_response(
        self, request_seq: int, *, timeout: float = 10.0
    ) -> dict[str, Any]:
        """Wait for a response to a previously sent request."""
        response_queue = self._pending.get(request_seq)
        if response_queue is None:
            raise DAPError(f'No pending DAP request: {request_seq}')
        try:
            response = response_queue.get(timeout=timeout)
        except queue.Empty as exc:
            raise DAPError(f'DAP request {request_seq} timed out') from exc
        finally:
            with self._lock:
                self._pending.pop(request_seq, None)
        if not response.get('success', False):
            message = response.get('message') or response.get('body', {}).get('error')
            raise DAPError(str(message or f'DAP request {request_seq} failed'))
        return response

    def wait_for_event(
        self,
        event: str,
        *,
        timeout: float = 10.0,
        predicate: Callable[[dict[str, Any]], bool] | None = None,
    ) -> dict[str, Any] | None:
        """Wait until an event with the given name is observed."""
        end_time = time.monotonic() + timeout
        with self._event_condition:
            seen = 0
            while True:
                for message in self._events[seen:]:
                    if message.get('event') == event and (
                        predicate is None or predicate(message)
                    ):
                        return message
                seen = len(self._events)
                remaining = end_time - time.monotonic()
                if remaining <= 0:
                    return None
                self._event_condition.wait(timeout=remaining)

    def drain_events(self) -> list[dict[str, Any]]:
        """Return and clear buffered DAP events."""
        with self._event_condition:
            events = list(self._events)
            self._events.clear()
            return events

    def stderr_tail(self, limit: int = 20) -> list[str]:
        """Return recent adapter stderr lines."""
        with self._lock:
            return self._stderr[-limit:]

    def _send(self, message: dict[str, Any]) -> None:
        process = self.process
        if process is None or process.stdin is None:
            raise DAPError('DAP adapter is not running')
        payload = json.dumps(message, separators=(',', ':')).encode('utf-8')
        header = f'Content-Length: {len(payload)}\r\n\r\n'.encode('ascii')
        try:
            process.stdin.write(header + payload)
            process.stdin.flush()
        except BrokenPipeError as exc:
            raise DAPError('DAP adapter pipe closed') from exc

    def _reader_loop(self) -> None:
        while not self._closed:
            try:
                message = self._read_message()
            except Exception as exc:
                if not self._closed:
                    logger.debug('DAP reader stopped: %s', exc, exc_info=True)
                return
            if message is None:
                return
            self._handle_message(message)

    def _stderr_loop(self) -> None:
        process = self.process
        if process is None or process.stderr is None:
            return
        while not self._closed:
            line = process.stderr.readline()
            if not line:
                return
            with self._lock:
                self._stderr.append(line.decode('utf-8', errors='replace').rstrip())
                del self._stderr[:-100]

    def _read_message(self) -> dict[str, Any] | None:
        process = self.process
        if process is None or process.stdout is None:
            return None
        content_length: int | None = None
        while True:
            line = process.stdout.readline()
            if not line:
                return None
            if line in (b'\r\n', b'\n'):
                break
            text = line.decode('ascii', errors='replace').strip()
            key, _, value = text.partition(':')
            if key.lower() == 'content-length':
                content_length = int(value.strip())
        if content_length is None:
            raise DAPError('DAP message missing Content-Length')
        payload = process.stdout.read(content_length)
        if len(payload) != content_length:
            raise DAPError('DAP message payload ended early')
        return json.loads(payload.decode('utf-8'))

    def _handle_message(self, message: dict[str, Any]) -> None:
        message_type = message.get('type')
        if message_type == 'response':
            request_seq = int(message.get('request_seq', -1))
            response_queue = self._pending.get(request_seq)
            if response_queue is not None:
                response_queue.put(message)
            return
        if message_type == 'event':
            with self._event_condition:
                self._events.append(message)
                self._event_condition.notify_all()


class DAPDebugSession:
    """Stateful DAP session controlled through standard DAP requests."""

    def __init__(
        self,
        session_id: str,
        *,
        workspace_root: str,
        adapter_command: list[str],
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
        self.client = DAPClient(adapter_command, cwd=self.cwd or str(self.workspace_root))
        self.current_thread_id: int | None = None
        self.debuggee_process_ids: set[int] = set()
        self.start_request_seq: int | None = None
        self._set_initial_breakpoints(breakpoints)

    def start(self, timeout: float = 15.0) -> dict[str, Any]:
        """Start the adapter, send launch/attach, and configure breakpoints."""
        self.client.start()
        self.client.request('initialize', self._initialize_arguments(), timeout=timeout)
        self.start_request_seq = self.client.request_nowait(
            self.request, self._start_arguments()
        )
        initialized = self.client.wait_for_event('initialized', timeout=timeout)
        if initialized is None:
            raise DAPError('DAP adapter did not send initialized event')
        breakpoint_results = self._sync_all_breakpoints(timeout=timeout)
        self.client.request('configurationDone', {}, timeout=timeout)
        if self.start_request_seq is not None:
            try:
                self.client.wait_for_response(
                    self.start_request_seq, timeout=min(timeout, 1.0)
                )
            except DAPError:
                logger.debug('DAP start response was not available yet', exc_info=True)
        event = self._wait_for_pause_or_exit(timeout=0.5)
        return self._snapshot(
            state='started',
            extra={'breakpoints': breakpoint_results, 'event': event},
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

    def pause(self, thread_id: int | None = None, timeout: float = 10.0) -> dict[str, Any]:
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

    def _sync_all_breakpoints(self, timeout: float) -> dict[str, Any]:
        results: dict[str, Any] = {}
        for source_path, breakpoints in self.breakpoints_by_file.items():
            response = self.client.request(
                'setBreakpoints',
                {
                    'source': {'path': source_path},
                    'breakpoints': breakpoints,
                    'sourceModified': False,
                },
                timeout=timeout,
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

    def _snapshot(self, state: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
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
        try:
            if debug_action == 'start':
                payload = self._start(action, timeout=max(timeout, 15.0))
            else:
                session = self._get_session(action.session_id)
                payload = self._dispatch_existing(session, action, debug_action, timeout)
            return self._observation(debug_action, payload)
        except Exception as exc:
            return ErrorObservation(f'Debugger error: {type(exc).__name__}: {exc}')

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
        adapter_id = action.adapter_id or adapter or 'generic'
        language = action.language or adapter

        session = DAPDebugSession(
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
        self.sessions[session_id] = session
        try:
            return session.start(timeout=timeout)
        except Exception:
            self.sessions.pop(session_id, None)
            session.close()
            raise

    def _dispatch_existing(
        self,
        session: DAPDebugSession,
        action: DebuggerAction,
        debug_action: str,
        timeout: float,
    ) -> dict[str, Any]:
        if debug_action == 'set_breakpoints':
            if not action.file:
                raise DAPError('set_breakpoints requires file')
            return session.set_breakpoints(
                action.file, action.lines, action.breakpoints or None, timeout=timeout
            )
        if debug_action == 'continue':
            return session.continue_execution(action.thread_id, timeout=timeout)
        if debug_action == 'next':
            return session.step('next', action.thread_id, timeout=timeout)
        if debug_action == 'step_in':
            return session.step('stepIn', action.thread_id, timeout=timeout)
        if debug_action == 'step_out':
            return session.step('stepOut', action.thread_id, timeout=timeout)
        if debug_action == 'pause':
            return session.pause(action.thread_id, timeout=timeout)
        if debug_action == 'stack':
            return session.stack_trace(action.thread_id, timeout=timeout)
        if debug_action == 'scopes':
            if action.frame_id is None:
                raise DAPError('scopes requires frame_id')
            return session.scopes(action.frame_id, timeout=timeout)
        if debug_action == 'variables':
            if action.variables_reference is None:
                raise DAPError('variables requires variables_reference')
            return session.variables(
                action.variables_reference, action.count, timeout=timeout
            )
        if debug_action == 'evaluate':
            if not action.expression:
                raise DAPError('evaluate requires expression')
            return session.evaluate(action.expression, action.frame_id, timeout=timeout)
        if debug_action == 'status':
            return session.status(timeout=timeout)
        if debug_action == 'stop':
            payload = session.stop(timeout=timeout)
            self.sessions.pop(session.session_id, None)
            return payload
        raise DAPError(f'Unknown debugger action: {debug_action}')

    def _adapter_name(self, action: DebuggerAction) -> str | None:
        adapter = action.adapter or action.language
        if adapter:
            return adapter.strip().lower()
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
        hint = f' for adapter {adapter!r}' if adapter else ''
        raise DAPError(
            'debugger start requires adapter_command'
            f'{hint}. Provide a DAP adapter command over stdio, or use adapter="python".'
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
