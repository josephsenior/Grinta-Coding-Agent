"""DAPClient — DAP protocol implementation.

Extracted from backend/execution/debugger.py to keep the parent module
under the per-file LOC budget.
"""

from __future__ import annotations

import json
import logging
import queue
import socket
import subprocess
import threading
import time
from collections.abc import Callable
from typing import Any

from backend.core.logging.logger import app_logger as logger
from backend.execution.dap._dap_errors import DAPError
from backend.execution.dap._dap_logging import _dap_log
from backend.execution.dap._dap_spawn_utils import (
    format_adapter_spawn_error,
    resolve_adapter_cwd,
)
from backend.utils.path_normalize import to_native_path


class DAPClient:
    """Minimal DAP client that talks to a debug adapter over stdio or TCP."""

    def __init__(
        self,
        adapter_command: list[str],
        cwd: str | None = None,
        *,
        transport: str = 'stdio',
        host: str | None = None,
        port: int | None = None,
    ) -> None:
        self.adapter_command = adapter_command
        self.cwd = cwd
        self.transport = transport
        self.host = host or '127.0.0.1'
        self.port = int(port) if port is not None else None
        self.process: subprocess.Popen[bytes] | None = None
        self._socket: socket.socket | None = None
        self._socket_file: Any | None = None
        self._seq = 0
        self._pending: dict[int, queue.Queue[dict[str, Any]]] = {}
        self._events: list[dict[str, Any]] = []
        self._stderr: list[str] = []
        self._lock = threading.RLock()
        self._event_condition = threading.Condition(self._lock)
        self._reader: threading.Thread | None = None
        self._stderr_reader: threading.Thread | None = None
        self._stdout_reader: threading.Thread | None = None
        self._closed = False

    def start(self) -> None:
        """Start the adapter subprocess and reader threads."""
        if self.process is not None or self._socket is not None:
            return
        if self.transport not in {'stdio', 'tcp'}:
            raise DAPError(f'Unsupported DAP adapter transport: {self.transport}')
        if not self.adapter_command and self.transport != 'tcp':
            raise DAPError('DAP adapter command is empty')
        if self.transport == 'tcp' and self.port is None:
            raise DAPError('TCP DAP adapter transport requires a port')
        _dap_log(
            logging.INFO,
            f'starting adapter over {self.transport} (cwd={self.cwd})',
            msg_type='DAP_ADAPTER_SPAWN',
            adapter_argv0=self.adapter_command[0] if self.adapter_command else None,
            dap_cwd=self.cwd,
            dap_transport=self.transport,
            dap_host=self.host if self.transport == 'tcp' else None,
            dap_port=self.port if self.transport == 'tcp' else None,
        )
        spawn_started = time.monotonic()
        output_readers_started = False
        try:
            if self.adapter_command:
                self.process = self._spawn_adapter()
                if self.transport == 'tcp':
                    self._start_output_readers()
                    output_readers_started = True
            if self.transport == 'tcp':
                self._connect_tcp()
            else:
                self._verify_stdio_process()
        except DAPError:
            self.close()
            raise
        except (OSError, ValueError) as exc:
            # ``Popen`` itself can fail (e.g. executable missing on Windows,
            # invalid argv). No subprocess exists yet, but raise a typed error
            # so the caller can surface a useful message instead of swallowing
            # ``FileNotFoundError`` deep in the stack.
            self.process = None
            raise DAPError(
                format_adapter_spawn_error(
                    exc,
                    command=self.adapter_command,
                    cwd=self.cwd,
                )
            ) from exc
        except Exception:
            self.close()
            raise
        try:
            self._reader = threading.Thread(target=self._reader_loop, daemon=True)
            self._reader.start()
            if not output_readers_started:
                self._start_output_readers()
        except Exception:
            # Reader thread creation failure is exotic but recoverable: kill
            # the half-spawned subprocess so we never leak a debugpy.adapter.
            self.close()
            raise
        _dap_log(
            logging.INFO,
            'adapter transport ready after start',
            msg_type='DAP_ADAPTER_SPAWN',
            adapter_pid=getattr(self.process, 'pid', None),
            dap_transport=self.transport,
            spawn_elapsed_seconds=round(time.monotonic() - spawn_started, 3),
        )

    def _spawn_adapter(self) -> subprocess.Popen[bytes]:
        stdin = subprocess.PIPE if self.transport == 'stdio' else subprocess.DEVNULL
        cwd = resolve_adapter_cwd(self.cwd)
        self.cwd = cwd
        command = [to_native_path(str(c)) for c in self.adapter_command]
        return subprocess.Popen(
            command,
            cwd=cwd,
            stdin=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def _verify_stdio_process(self) -> None:
        if (
            self.process is None
            or self.process.stdin is None
            or self.process.stdout is None
        ):
            raise DAPError('DAP stdio adapter did not expose stdin/stdout pipes')

    def _connect_tcp(self) -> None:
        if self.port is None:
            raise DAPError('TCP DAP adapter transport requires a port')
        deadline = time.monotonic() + 5.0
        while True:
            process = self.process
            if process is not None and process.poll() is not None:
                raise DAPError(
                    'DAP TCP adapter exited before accepting a connection '
                    f'(exit={process.poll()})'
                )
            try:
                sock = socket.create_connection((self.host, self.port), timeout=0.25)
                sock.settimeout(None)
                self._socket = sock
                self._socket_file = sock.makefile('rwb', buffering=0)
                return
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise DAPError(
                        f'Failed to connect to DAP adapter at '
                        f'{self.host}:{self.port}: {exc}'
                    ) from exc
                time.sleep(0.05)

    def _start_output_readers(self) -> None:
        if self.process is None:
            return
        self._stderr_reader = threading.Thread(target=self._stderr_loop, daemon=True)
        self._stderr_reader.start()
        if self.transport == 'tcp':
            self._stdout_reader = threading.Thread(
                target=self._stdout_log_loop, daemon=True
            )
            self._stdout_reader.start()

    def close(self) -> None:
        """Terminate the adapter subprocess."""
        self._closed = True
        self._close_socket()
        process = self.process
        try:
            if process is not None and process.poll() is None:
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
            for reader in (self._reader, self._stderr_reader, self._stdout_reader):
                if reader is not None and reader.is_alive():
                    try:
                        reader.join(timeout=1.0)
                    except Exception:
                        pass
            self._reader = None
            self._stderr_reader = None
            self._stdout_reader = None

    def _close_socket(self) -> None:
        socket_file = self._socket_file
        sock = self._socket
        self._socket_file = None
        self._socket = None
        try:
            if socket_file is not None:
                socket_file.close()
        except Exception:
            pass
        try:
            if sock is not None:
                sock.close()
        except Exception:
            pass
        with self._lock:
            self._event_condition.notify_all()

    def is_running(self) -> bool:
        """Return whether the adapter transport still appears usable."""
        if self._closed:
            return False
        if self.transport == 'tcp' and self._socket is not None:
            return self.process is None or self.process.poll() is None
        return self.process is not None and self.process.poll() is None

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
            _dap_log(
                logging.WARNING,
                'DAP wait_for_response timed out',
                msg_type='DAP_RESPONSE_TIMEOUT',
                request_seq=request_seq,
                timeout_seconds=timeout,
                pending_count=len(self._pending),
                stderr_tail=self.stderr_tail(10),
                process_alive=(self.is_running()),
            )
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
                matched = self._find_matching_event(event, predicate, seen)
                if matched is not None:
                    return matched
                seen = len(self._events)
                remaining = end_time - time.monotonic()
                if remaining <= 0:
                    self._log_event_timeout(event)
                    return None
                self._event_condition.wait(timeout=remaining)

    def _find_matching_event(
        self,
        event: str,
        predicate: Callable[[dict[str, Any]], bool] | None,
        seen: int,
    ) -> dict[str, Any] | None:
        for message in self._events[seen:]:
            if message.get('event') == event and (
                predicate is None or predicate(message)
            ):
                return message
        return None

    def _log_event_timeout(self, event: str) -> None:
        ev_names = [str(m.get('event') or '?') for m in self._events]
        proc = self.process
        alive = self.is_running()
        poll = proc.poll() if proc is not None else None
        _dap_log(
            logging.WARNING,
            'DAP wait_for_event timed out',
            msg_type='DAP_EVENT_TIMEOUT',
            wanted_event=event,
            buffered_event_count=len(self._events),
            buffered_events_tail=ev_names[-15:],
            process_alive=alive,
            process_poll=poll,
            stderr_tail=self.stderr_tail(5),
        )

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
        payload = json.dumps(message, separators=(',', ':')).encode('utf-8')
        header = f'Content-Length: {len(payload)}\r\n\r\n'.encode('ascii')
        try:
            if self.transport == 'tcp':
                if self._socket is None:
                    raise DAPError('DAP adapter is not running')
                self._socket.sendall(header + payload)
            else:
                process = self.process
                if process is None or process.stdin is None:
                    raise DAPError('DAP adapter is not running')
                process.stdin.write(header + payload)
                process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise DAPError('DAP adapter connection closed') from exc

    def _reader_loop(self) -> None:
        while not self._closed:
            try:
                message = self._read_message()
            except Exception as exc:
                if not self._closed:
                    logger.debug('DAP reader stopped: %s', exc, exc_info=True)
                return
            if message is None:
                _dap_log(
                    logging.INFO,
                    'DAP adapter message stream closed (EOF)',
                    msg_type='DAP_ADAPTER_EOF',
                    dap_transport=self.transport,
                    process_alive=self.is_running(),
                    process_poll=(
                        None if self.process is None else self.process.poll()
                    ),
                )
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

    def _stdout_log_loop(self) -> None:
        process = self.process
        if process is None or process.stdout is None:
            return
        while not self._closed:
            line = process.stdout.readline()
            if not line:
                return
            with self._lock:
                decoded = line.decode('utf-8', errors='replace').rstrip()
                self._stderr.append(f'[stdout] {decoded}')
                del self._stderr[:-100]

    def _read_message(self) -> dict[str, Any] | None:
        stream = self._message_stream()
        if stream is None:
            return None
        content_length: int | None = None
        while True:
            line = stream.readline()
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
        payload = stream.read(content_length)
        if len(payload) != content_length:
            raise DAPError('DAP message payload ended early')
        return json.loads(payload.decode('utf-8'))

    def _message_stream(self) -> Any | None:
        if self.transport == 'tcp':
            return self._socket_file
        process = self.process
        if process is None:
            return None
        return process.stdout

    def _handle_message(self, message: dict[str, Any]) -> None:
        message_type = message.get('type')
        if message_type == 'response':
            request_seq = int(message.get('request_seq', -1))
            response_queue = self._pending.get(request_seq)
            if response_queue is not None:
                response_queue.put(message)
            return
        if message_type == 'event':
            ev = str(message.get('event') or '')
            if ev in {'initialized', 'stopped', 'terminated', 'process'}:
                logger.debug(
                    'DAP event: %s seq=%s',
                    ev,
                    message.get('seq'),
                    extra={'msg_type': 'DAP_EVENT', 'dap_event': ev},
                )
            with self._event_condition:
                self._events.append(message)
                self._event_condition.notify_all()
