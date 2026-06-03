"""Tests for the DAP debug manager."""

from __future__ import annotations

import logging
from typing import Any

from backend.execution import debugger as debugger_module
from backend.execution.debugger import DAPClient, DAPDebugManager, DAPStartPhaseError
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

    monkeypatch.setattr('backend.execution._dap_manager.DAPDebugSession', FakeSession)
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

    monkeypatch.setattr('backend.execution._dap_manager.DAPDebugSession', FakeSession)
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

    monkeypatch.setattr('backend.execution._dap_manager.DAPDebugSession', FakeSession)
    monkeypatch.setattr(
        'backend.execution._dap_adapters.shutil.which',
        lambda cmd: '/fake/js-debug-adapter' if cmd == 'js-debug-adapter' else None,
    )

    manager = DAPDebugManager(str(tmp_path))
    start_obs = manager.handle(
        DebuggerAction(debug_action='start', adapter='pwa-node', session_id='dbg-pwa')
    )
    assert isinstance(start_obs, DebuggerObservation)
    assert instances[0].kwargs['adapter_command'] == ['/fake/js-debug-adapter']
    assert instances[0].kwargs['adapter_id'] == 'javascript'


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

    monkeypatch.setattr('backend.execution._dap_manager.DAPDebugSession', FakeSession)
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
