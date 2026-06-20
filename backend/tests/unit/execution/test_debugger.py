"""Tests for the DAP debug manager."""

from __future__ import annotations

import logging
import sys
import textwrap
from typing import Any

from backend.execution.server import debugger as debugger_module
from backend.execution.dap._dap_adapters import (
    _resolve_recipe,
    build_custom_adapter_spec,
    detect_debug_adapters,
)
from backend.execution.server.debugger import (
    DAPClient,
    DAPDebugManager,
    DAPError,
    DAPStartPhaseError,
)
from backend.ledger.action.debugger import DebuggerAction, is_debugger_action
from backend.ledger.observation import ErrorObservation
from backend.ledger.observation.debugger import DebuggerObservation


def test_dap_log_renames_reserved_logrecord_extra_keys(monkeypatch: Any) -> None:
    """``logging`` forbids ``extra`` keys that collide with ``LogRecord`` attributes."""
    captured: dict[str, Any] = {}

    def fake_log(level: int, msg: str, extra: dict[str, Any] | None = None) -> None:
        captured['level'] = level
        captured['msg'] = msg
        captured['extra'] = dict(extra or {})

    monkeypatch.setattr(debugger_module.logger, 'log', fake_log)
    debugger_module._dap_log(
        logging.INFO,
        'probe',
        msg_type='TEST',
        filename='would_collide.py',
        module='also_collides',
    )
    extra = captured['extra']
    assert 'filename' not in extra
    assert 'module' not in extra
    assert extra.get('dap_filename') == 'would_collide.py'
    assert extra.get('dap_module') == 'also_collides'


def test_dap_client_send_request_frames_content_length() -> None:
    client = DAPClient(['python', '-m', 'debugpy.adapter'])
    writes: list[bytes] = []

    class FakeStdin:
        def write(self, data: bytes) -> None:
            writes.append(data)

        def flush(self) -> None:
            return None

    class FakeProcess:
        stdin = FakeStdin()

    client.process = FakeProcess()  # type: ignore[assignment]
    client.request_nowait('threads', {})
    assert writes
    assert writes[0].startswith(b'Content-Length: ')
    assert b'"command":"threads"' in writes[0]


def test_dap_client_send_request_frames_over_tcp() -> None:
    client = DAPClient([], transport='tcp', host='127.0.0.1', port=12345)
    writes: list[bytes] = []

    class FakeSocket:
        def sendall(self, data: bytes) -> None:
            writes.append(data)

    client._socket = FakeSocket()  # type: ignore[assignment]
    client.request_nowait('threads', {})
    assert writes
    assert writes[0].startswith(b'Content-Length: ')
    assert b'"command":"threads"' in writes[0]


def test_custom_tcp_adapter_spec_substitutes_allocated_port(monkeypatch) -> None:
    monkeypatch.setattr(
        'backend.execution.dap._dap_adapters._reserve_local_tcp_port',
        lambda: 45681,
    )

    spec = build_custom_adapter_spec(
        ['adapter', '--listen', '127.0.0.1:{port}'],
        transport='tcp',
    )

    assert spec.command == ['adapter', '--listen', '127.0.0.1:45681']
    assert spec.transport == 'tcp'
    assert spec.host == '127.0.0.1'
    assert spec.port == 45681


def test_custom_tcp_adapter_requires_port_or_placeholder() -> None:
    try:
        build_custom_adapter_spec(['adapter', '--tcp'], transport='tcp')
    except ValueError as exc:
        assert '{port}' in str(exc)
    else:
        raise AssertionError('Expected missing TCP port placeholder to fail')


def test_manager_start_and_status_with_generic_adapter(monkeypatch, tmp_path) -> None:
    instances: list[Any] = []

    class FakeSession:
        def __init__(self, session_id: str, **kwargs: Any) -> None:
            self.session_id = session_id
            self.kwargs = kwargs
            instances.append(self)

        def start(self, timeout: float = 15.0) -> dict[str, Any]:
            return {
                'session_id': self.session_id,
                'state': 'started',
                'timeout': timeout,
            }

        def status(self, timeout: float = 5.0) -> dict[str, Any]:
            return {'session_id': self.session_id, 'state': 'status', 'threads': []}

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        'backend.execution.dap._dap_manager.DAPDebugSession', FakeSession
    )
    manager = DAPDebugManager(str(tmp_path))

    start_obs = manager.handle(
        DebuggerAction(
            debug_action='start',
            adapter='node',
            adapter_id='pwa-node',
            adapter_command=['node', 'adapter.js'],
            launch_config={'type': 'pwa-node', 'program': 'server.js'},
            session_id='dbg-test',
        )
    )
    assert isinstance(start_obs, DebuggerObservation)
    assert start_obs.session_id == 'dbg-test'
    assert manager.sessions['dbg-test'] is instances[0]
    assert instances[0].kwargs['adapter_command'] == ['node', 'adapter.js']
    assert instances[0].kwargs['adapter_id'] == 'pwa-node'
    assert instances[0].kwargs['launch_config'] == {
        'type': 'pwa-node',
        'program': 'server.js',
    }

    status_obs = manager.handle(
        DebuggerAction(debug_action='status', session_id='dbg-test')
    )
    assert isinstance(status_obs, DebuggerObservation)
    assert status_obs.state == 'status'


def test_manager_infers_python_preset_for_py_program(monkeypatch, tmp_path) -> None:
    instances: list[Any] = []

    class FakeSession:
        def __init__(self, session_id: str, **kwargs: Any) -> None:
            self.session_id = session_id
            self.kwargs = kwargs
            instances.append(self)

        def start(self, timeout: float = 15.0) -> dict[str, Any]:
            return {'session_id': self.session_id, 'state': 'started'}

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        'backend.execution.dap._dap_manager.DAPDebugSession', FakeSession
    )
    manager = DAPDebugManager(str(tmp_path))

    start_obs = manager.handle(
        DebuggerAction(debug_action='start', program='app.py', session_id='dbg-python')
    )
    assert isinstance(start_obs, DebuggerObservation)
    assert instances[0].kwargs['adapter_id'] == 'python'
    assert instances[0].kwargs['language'] == 'python'
    assert instances[0].kwargs['adapter_command'][1:] == ['-m', 'debugpy.adapter']


def test_manager_requires_adapter_command_for_non_python(tmp_path) -> None:
    manager = DAPDebugManager(str(tmp_path))
    obs = manager.handle(DebuggerAction(debug_action='start', adapter='node'))
    assert isinstance(obs, ErrorObservation)
    assert 'adapter_command' in obs.content


def test_manager_maps_pwa_node_adapter_to_js_recipe(monkeypatch, tmp_path) -> None:
    instances: list[Any] = []

    class FakeSession:
        def __init__(self, session_id: str, **kwargs: Any) -> None:
            self.session_id = session_id
            self.kwargs = kwargs
            instances.append(self)

        def start(self, timeout: float = 15.0) -> dict[str, Any]:
            return {'session_id': self.session_id, 'state': 'started'}

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        'backend.execution.dap._dap_manager.DAPDebugSession', FakeSession
    )
    monkeypatch.setattr(
        'backend.execution.dap._dap_adapters.shutil.which',
        lambda cmd: '/fake/js-debug-adapter' if cmd == 'js-debug-adapter' else None,
    )

    manager = DAPDebugManager(str(tmp_path))
    start_obs = manager.handle(
        DebuggerAction(debug_action='start', adapter='pwa-node', session_id='dbg-pwa')
    )
    assert isinstance(start_obs, DebuggerObservation)
    assert instances[0].kwargs['adapter_command'] == ['/fake/js-debug-adapter']
    assert instances[0].kwargs['adapter_id'] == 'javascript'


def test_resolve_recipe_supports_tcp_adapter(monkeypatch) -> None:
    monkeypatch.setattr(
        'backend.execution.dap._dap_adapters.shutil.which',
        lambda cmd: '/fake/dlv' if cmd == 'dlv' else None,
    )
    monkeypatch.setattr(
        'backend.execution.dap._dap_adapters._reserve_local_tcp_port',
        lambda: 45678,
    )

    assert _resolve_recipe('go') == [
        '/fake/dlv',
        'dap',
        '--listen=127.0.0.1:45678',
    ]
    go_entry = next(
        entry for entry in detect_debug_adapters() if entry['language'] == 'go'
    )
    assert go_entry['available'] is True
    assert go_entry['auto_resolvable'] is True
    assert go_entry['transport'] == 'tcp'
    assert go_entry['command'] == ['/fake/dlv', 'dap', '--listen=127.0.0.1:0']
    assert go_entry['unsupported_reason'] == ''


def test_resolve_recipe_prefers_tcp_codelldb(monkeypatch) -> None:
    def fake_which(cmd: str) -> str | None:
        if cmd == 'codelldb':
            return '/fake/codelldb'
        if cmd == 'lldb-dap':
            return '/fake/lldb-dap'
        return None

    monkeypatch.setattr('backend.execution.dap._dap_adapters.shutil.which', fake_which)
    monkeypatch.setattr(
        'backend.execution.dap._dap_adapters._reserve_local_tcp_port',
        lambda: 45679,
    )

    assert _resolve_recipe('rust') == ['/fake/codelldb', '--port', '45679']
    rust_entry = next(
        entry for entry in detect_debug_adapters() if entry['language'] == 'rust'
    )
    assert rust_entry['adapter'] == 'codelldb'
    assert rust_entry['auto_resolvable'] is True
    assert rust_entry['transport'] == 'tcp'


def test_resolve_recipe_falls_back_to_stdio_when_tcp_missing(monkeypatch) -> None:
    def fake_which(cmd: str) -> str | None:
        if cmd == 'lldb-dap':
            return '/fake/lldb-dap'
        return None

    monkeypatch.setattr('backend.execution.dap._dap_adapters.shutil.which', fake_which)

    assert _resolve_recipe('rust') == ['/fake/lldb-dap']
    rust_entry = next(
        entry for entry in detect_debug_adapters() if entry['language'] == 'rust'
    )
    assert rust_entry['adapter'] == 'lldb-dap'
    assert rust_entry['transport'] == 'stdio'


def test_detect_debug_adapters_keeps_rdbg_diagnostic_only(monkeypatch) -> None:
    monkeypatch.setattr(
        'backend.execution.dap._dap_adapters.shutil.which',
        lambda cmd: '/fake/rdbg' if cmd == 'rdbg' else None,
    )
    ruby_entry = next(
        entry for entry in detect_debug_adapters() if entry['language'] == 'ruby'
    )

    assert ruby_entry['available'] is True
    assert ruby_entry['auto_resolvable'] is False
    assert ruby_entry['transport'] == 'ruby-debug'
    assert 'DAP-over-TCP' in ruby_entry['unsupported_reason']


def test_manager_autoresolves_tcp_adapter(monkeypatch, tmp_path) -> None:
    instances: list[Any] = []

    class FakeSession:
        def __init__(self, session_id: str, **kwargs: Any) -> None:
            self.session_id = session_id
            self.kwargs = kwargs
            instances.append(self)

        def start(self, timeout: float = 15.0) -> dict[str, Any]:
            return {'session_id': self.session_id, 'state': 'started'}

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        'backend.execution.dap._dap_manager.DAPDebugSession', FakeSession
    )
    monkeypatch.setattr(
        'backend.execution.dap._dap_adapters.shutil.which',
        lambda cmd: '/fake/dlv' if cmd == 'dlv' else None,
    )
    monkeypatch.setattr(
        'backend.execution.dap._dap_adapters._reserve_local_tcp_port',
        lambda: 45680,
    )
    manager = DAPDebugManager(str(tmp_path))

    obs = manager.handle(
        DebuggerAction(debug_action='start', adapter='go', session_id='dbg-go')
    )

    assert isinstance(obs, DebuggerObservation)
    assert instances[0].kwargs['adapter_command'] == [
        '/fake/dlv',
        'dap',
        '--listen=127.0.0.1:45680',
    ]
    assert instances[0].kwargs['adapter_transport'] == 'tcp'
    assert instances[0].kwargs['adapter_host'] == '127.0.0.1'
    assert instances[0].kwargs['adapter_port'] == 45680


def test_manager_starts_minimal_tcp_adapter(tmp_path) -> None:
    adapter_script = tmp_path / 'fake_tcp_dap.py'
    adapter_script.write_text(
        textwrap.dedent(
            r"""
            import json
            import socket
            import sys

            def recv_message(conn):
                header = b''
                while b'\r\n\r\n' not in header:
                    chunk = conn.recv(1)
                    if not chunk:
                        return None
                    header += chunk
                content_length = None
                for line in header.decode('ascii').split('\r\n'):
                    key, _, value = line.partition(':')
                    if key.lower() == 'content-length':
                        content_length = int(value.strip())
                if content_length is None:
                    return None
                payload = b''
                while len(payload) < content_length:
                    chunk = conn.recv(content_length - len(payload))
                    if not chunk:
                        return None
                    payload += chunk
                return json.loads(payload.decode('utf-8'))

            def send_message(conn, message):
                payload = json.dumps(message, separators=(',', ':')).encode('utf-8')
                conn.sendall(
                    b'Content-Length: '
                    + str(len(payload)).encode('ascii')
                    + b'\r\n\r\n'
                    + payload
                )

            port = int(sys.argv[1])
            seq = 1

            def next_seq():
                global seq
                current = seq
                seq += 1
                return current

            def respond(conn, request, body=None):
                send_message(
                    conn,
                    {
                        'seq': next_seq(),
                        'type': 'response',
                        'request_seq': request['seq'],
                        'command': request['command'],
                        'success': True,
                        'body': body or {},
                    },
                )

            def emit(conn, event, body=None):
                send_message(
                    conn,
                    {
                        'seq': next_seq(),
                        'type': 'event',
                        'event': event,
                        'body': body or {},
                    },
                )

            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
                server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                server.bind(('127.0.0.1', port))
                server.listen(1)
                conn, _addr = server.accept()
                with conn:
                    while True:
                        request = recv_message(conn)
                        if request is None:
                            break
                        command = request.get('command')
                        if command == 'initialize':
                            respond(conn, request, {'supportsConfigurationDoneRequest': True})
                        elif command in {'launch', 'attach'}:
                            emit(conn, 'initialized')
                            respond(conn, request)
                        elif command == 'configurationDone':
                            respond(conn, request)
                            emit(conn, 'stopped', {'threadId': 1, 'reason': 'entry'})
                        elif command == 'threads':
                            respond(conn, request, {'threads': [{'id': 1, 'name': 'main'}]})
                        elif command == 'disconnect':
                            respond(conn, request)
                            emit(conn, 'terminated')
                            break
                        else:
                            respond(conn, request)
            """
        ),
        encoding='utf-8',
    )
    manager = DAPDebugManager(str(tmp_path))

    start_obs = manager.handle(
        DebuggerAction(
            debug_action='start',
            adapter='fake',
            adapter_command=[sys.executable, str(adapter_script), '{port}'],
            adapter_transport='tcp',
            session_id='dbg-tcp',
            launch_config={'type': 'fake'},
            timeout=5,
        )
    )
    try:
        assert isinstance(start_obs, DebuggerObservation)
        assert start_obs.state == 'started'
        event_names = [event.get('event') for event in start_obs.payload['events']]
        assert 'stopped' in event_names
    finally:
        manager.close_all()


def test_manager_keeps_live_session_after_nonfatal_request_error(tmp_path) -> None:
    class FakeProcess:
        def poll(self) -> None:
            return None

    class FakeClient:
        process = FakeProcess()

        def stderr_tail(self, limit: int = 20) -> list[str]:
            return []

    class FakeSession:
        session_id = 'dbg-live'
        client = FakeClient()
        closed = False

        def evaluate(
            self, expression: str, frame_id: int | None = None, timeout: float = 10.0
        ) -> dict[str, Any]:
            raise DAPError('invalid expression')

        def close(self) -> None:
            self.closed = True

    manager = DAPDebugManager(str(tmp_path))
    session = FakeSession()
    manager.sessions[session.session_id] = session  # type: ignore[assignment]

    obs = manager.handle(
        DebuggerAction(
            debug_action='evaluate',
            session_id=session.session_id,
            expression='bad +',
        )
    )

    assert isinstance(obs, ErrorObservation)
    assert manager.sessions[session.session_id] is session
    assert session.closed is False


def test_manager_start_error_includes_startup_phase_metadata(
    monkeypatch, tmp_path
) -> None:
    class FakeSession:
        def __init__(self, session_id: str, **kwargs: Any) -> None:
            self.session_id = session_id
            self.kwargs = kwargs

        def start(self, timeout: float = 15.0) -> dict[str, Any]:
            raise DAPStartPhaseError(
                'initialized event',
                'DAP adapter did not send initialized event',
                timeout=timeout,
            )

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        'backend.execution.dap._dap_manager.DAPDebugSession', FakeSession
    )
    manager = DAPDebugManager(str(tmp_path))
    obs = manager.handle(
        DebuggerAction(debug_action='start', program='app.py', session_id='dbg-phase')
    )
    assert isinstance(obs, ErrorObservation)
    assert 'startup_phase: initialized event' in obs.content
    assert 'startup_timeout_seconds' in obs.content


def test_is_debugger_action_string_tool_id_and_instance_attr() -> None:
    """Duplicate classes / replay paths may expose ``action`` as str or only on instance."""

    class OtherDebugger:
        action = 'debugger'

    assert is_debugger_action(OtherDebugger()) is True

    class Shell:
        pass

    inst = Shell()
    inst.action = 'debugger'  # type: ignore[attr-defined]
    assert is_debugger_action(inst) is True


def test_is_debugger_action_name_fallback_for_duplicate_module_load() -> None:
    """Last resort: distinct class objects both named ``DebuggerAction``."""
    ns: dict[str, Any] = {}
    exec(
        'from backend.core.schemas import ActionType\n'
        'class DebuggerAction:\n'
        '    action = ActionType.DEBUGGER\n',
        ns,
    )
    FakeCls = ns['DebuggerAction']
    assert is_debugger_action(FakeCls()) is True
