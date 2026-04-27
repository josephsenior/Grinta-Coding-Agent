"""Tests for the DAP debug manager."""

from __future__ import annotations

from typing import Any

from backend.execution.debugger import DAPClient, DAPDebugManager
from backend.ledger.action.debugger import DebuggerAction
from backend.ledger.observation import ErrorObservation
from backend.ledger.observation.debugger import DebuggerObservation


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


def test_manager_start_and_status_with_generic_adapter(monkeypatch, tmp_path) -> None:
    instances: list[Any] = []

    class FakeSession:
        def __init__(self, session_id: str, **kwargs: Any) -> None:
            self.session_id = session_id
            self.kwargs = kwargs
            instances.append(self)

        def start(self, timeout: float = 15.0) -> dict[str, Any]:
            return {'session_id': self.session_id, 'state': 'started', 'timeout': timeout}

        def status(self, timeout: float = 5.0) -> dict[str, Any]:
            return {'session_id': self.session_id, 'state': 'status', 'threads': []}

        def close(self) -> None:
            return None

    monkeypatch.setattr('backend.execution.debugger.DAPDebugSession', FakeSession)
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

    monkeypatch.setattr('backend.execution.debugger.DAPDebugSession', FakeSession)
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
