"""Tests for the Python debug manager."""

from __future__ import annotations

from typing import Any

from backend.execution.debugger import DAPClient, PythonDebugManager
from backend.ledger.action.debugger import DebuggerAction
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


def test_manager_start_and_status_with_fake_session(monkeypatch, tmp_path) -> None:
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

    monkeypatch.setattr('backend.execution.debugger.PythonDebugSession', FakeSession)
    manager = PythonDebugManager(str(tmp_path))

    start_obs = manager.handle(
        DebuggerAction(debug_action='start', program='app.py', session_id='dbg-test')
    )
    assert isinstance(start_obs, DebuggerObservation)
    assert start_obs.session_id == 'dbg-test'
    assert manager.sessions['dbg-test'] is instances[0]

    status_obs = manager.handle(
        DebuggerAction(debug_action='status', session_id='dbg-test')
    )
    assert isinstance(status_obs, DebuggerObservation)
    assert status_obs.state == 'status'
