"""Tests for the PTY-backed UnifiedShellSession adapter + factory wiring."""

from __future__ import annotations

import json
import os
import shutil
import time
from unittest.mock import MagicMock

import pytest

from backend.core.constants import CMD_OUTPUT_PS1_BEGIN, CMD_OUTPUT_PS1_END
from backend.execution.utils.pty_session import (
    InteractiveSessionError,
    PtyUnavailableError,
)
from backend.execution.utils.pty_shell_session import (
    _CONTROL_ALIASES,
    PtyInteractiveShellSession,
    _argv_looks_like_bash,
    _default_shell_argv,
    _output_between_last_two_ps1,
)
from backend.ledger.action.commands import CmdRunAction
from backend.ledger.observation import ErrorObservation
from backend.ledger.observation.commands import CmdOutputObservation

IS_WINDOWS = os.name == 'nt'


def _wait_for(condition, *, timeout: float = 5.0, interval: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(interval)
    return False


def _platform_backend_available() -> bool:
    try:
        if IS_WINDOWS:
            import winpty  # noqa: F401
        else:
            import ptyprocess  # noqa: F401
    except ImportError:
        return False
    return True


requires_pty = pytest.mark.skipif(
    not _platform_backend_available(),
    reason='platform PTY backend not installed',
)

requires_bash = pytest.mark.skipif(
    not shutil.which('bash'),
    reason='bash not on PATH',
)


def _ps1_block(payload: dict[str, str | int]) -> str:
    return (
        f'{CMD_OUTPUT_PS1_BEGIN.strip()}\n'
        f'{json.dumps(payload)}\n'
        f'{CMD_OUTPUT_PS1_END.strip()}\n'
    )


# ---------------------------------------------------------------------------
# Static / logic tests
# ---------------------------------------------------------------------------


class TestDefaultShellArgv:
    def test_returns_non_empty_list(self) -> None:
        argv = _default_shell_argv()
        assert isinstance(argv, list)
        assert len(argv) >= 1

    def test_returns_os_appropriate_shell(self) -> None:
        argv = _default_shell_argv()
        if IS_WINDOWS:
            assert any(
                tok.lower().endswith(
                    ('pwsh.exe', 'pwsh', 'powershell.exe', 'powershell', 'cmd.exe')
                )
                for tok in argv
            )
        else:
            assert (
                argv[0] in {'bash', 'sh'}
                or argv[0].endswith('/bash')
                or argv[0].endswith('/sh')
            )


class TestOutputBetweenLastTwoPs1:
    def test_parses_segment_and_exit(self) -> None:
        p1: dict[str, str | int] = {
            'pid': 100,
            'exit_code': 0,
            'username': 'u',
            'hostname': 'h',
            'working_dir': '/workspace',
            'py_interpreter_path': '/usr/bin/python',
        }
        p2 = {**p1, 'exit_code': 0, 'pid': 200}
        block1 = _ps1_block(p1)
        block2 = _ps1_block(p2)
        buf = f'{block1}echo grinta-ps1-slice\necho grinta-ps1-slice\n{block2}'
        out, meta = _output_between_last_two_ps1(buf, 'echo grinta-ps1-slice')
        assert 'grinta-ps1-slice' in out
        assert meta.exit_code == 0
        assert meta.working_dir == '/workspace'

    def test_too_few_blocks_returns_error_meta(self) -> None:
        out, meta = _output_between_last_two_ps1('nope', 'x')
        assert meta.exit_code == -1


class TestArgvLooksLikeBash:
    @pytest.mark.parametrize(
        'argv,expected',
        [
            (['/bin/bash'], True),
            ([r'C:\Program Files\Git\bin\bash.exe'], True),
            (['/bin/sh'], False),
            ([], False),
        ],
    )
    def test_detection(self, argv, expected) -> None:
        assert _argv_looks_like_bash(argv) is expected


class TestControlAliases:
    @pytest.mark.parametrize(
        ('raw', 'expected_key'),
        [
            ('C-c', 'c'),
            ('ctrl-c', 'c'),
            ('CTRL+C', 'c'),
            ('^c', 'c'),
            ('\x03', 'c'),
            ('C-d', 'd'),
            ('\x04', 'd'),
            ('esc', 'esc'),
            ('Tab', 'tab'),
            ('Enter', 'enter'),
        ],
    )
    def test_alias_normalization(self, raw: str, expected_key: str) -> None:
        normalized = raw.strip().lower() if len(raw) > 1 else raw
        assert _CONTROL_ALIASES[normalized] == expected_key


# ---------------------------------------------------------------------------
# Guards / error paths
# ---------------------------------------------------------------------------


class TestExecuteErrorPaths:
    def test_execute_before_initialize_returns_error_observation(
        self, tmp_path
    ) -> None:
        session = PtyInteractiveShellSession(work_dir=str(tmp_path))
        obs = session.execute(CmdRunAction(command='echo hi'))
        assert isinstance(obs, ErrorObservation)
        assert 'not initialized' in obs.content

    def test_execute_after_close_returns_error_observation(self, tmp_path) -> None:
        session = PtyInteractiveShellSession(work_dir=str(tmp_path))
        session._initialized = True
        session._closed = True
        obs = session.execute(CmdRunAction(command='echo hi'))
        assert isinstance(obs, ErrorObservation)

    def test_execute_with_dead_pty_returns_error_observation(self, tmp_path) -> None:
        session = PtyInteractiveShellSession(work_dir=str(tmp_path))
        session._initialized = True
        fake_pty = MagicMock()
        fake_pty.is_alive.return_value = False
        session._pty = fake_pty
        obs = session.execute(CmdRunAction(command='echo hi'))
        assert isinstance(obs, ErrorObservation)
        assert 'not alive' in obs.content

    def test_write_input_without_pty_logs_and_returns(self, tmp_path) -> None:
        session = PtyInteractiveShellSession(work_dir=str(tmp_path))
        # Should not raise even though _pty is None
        session.write_input('echo hi')
        session.write_input('C-c', is_control=True)

    def test_read_output_without_pty_returns_empty_string(self, tmp_path) -> None:
        session = PtyInteractiveShellSession(work_dir=str(tmp_path))
        assert session.read_output() == ''

    def test_write_input_recovers_from_underlying_error(self, tmp_path) -> None:
        session = PtyInteractiveShellSession(work_dir=str(tmp_path))
        fake_pty = MagicMock()
        fake_pty.write.side_effect = InteractiveSessionError('boom')
        session._pty = fake_pty
        session.write_input('echo hi')  # must swallow, not raise
        fake_pty.write.assert_called()


# ---------------------------------------------------------------------------
# Factory wiring
# ---------------------------------------------------------------------------


class TestFactoryWiring:
    def _make_tools(self) -> MagicMock:
        tools = MagicMock()
        tools.has_bash = False
        tools.has_powershell = True
        tools.has_tmux = False
        tools.shell_type = 'powershell'
        tools.is_container_runtime = False
        tools.is_wsl_runtime = False
        return tools

    def test_interactive_true_returns_pty_session(self, tmp_path) -> None:
        from backend.execution.utils.unified_shell import create_shell_session

        session = create_shell_session(
            work_dir=str(tmp_path),
            tools=self._make_tools(),
            interactive=True,
        )
        assert isinstance(session, PtyInteractiveShellSession)

    def test_interactive_false_preserves_legacy_selection(self, tmp_path) -> None:
        from backend.execution.utils.unified_shell import create_shell_session

        session = create_shell_session(
            work_dir=str(tmp_path),
            tools=self._make_tools(),
            interactive=False,
        )
        assert not isinstance(session, PtyInteractiveShellSession)

    def test_interactive_falls_back_when_pty_unavailable(
        self, tmp_path, monkeypatch
    ) -> None:
        from backend.execution.utils import unified_shell

        class _FakeRaisingPty:
            def __init__(self, *args, **kwargs):
                raise PtyUnavailableError('forced for test')

        monkeypatch.setattr(
            'backend.execution.utils.pty_shell_session.PtyInteractiveShellSession',
            _FakeRaisingPty,
        )

        session = unified_shell.create_shell_session(
            work_dir=str(tmp_path),
            tools=self._make_tools(),
            interactive=True,
        )
        assert not isinstance(session, PtyInteractiveShellSession)


class TestSessionManagerInteractiveFlag:
    def test_session_manager_passes_interactive_flag(
        self, tmp_path, monkeypatch
    ) -> None:
        from backend.execution.utils import session_manager as sm_mod

        captured: dict[str, object] = {}

        def fake_create_shell_session(**kwargs):
            captured.update(kwargs)
            fake = MagicMock()
            fake.initialize.return_value = None
            return fake

        monkeypatch.setattr(sm_mod, 'create_shell_session', fake_create_shell_session)

        manager = sm_mod.SessionManager(
            work_dir=str(tmp_path),
            username='test',
            tool_registry=MagicMock(),
        )
        manager.create_session(session_id='iface', cwd=str(tmp_path), interactive=True)
        assert captured.get('interactive') is True

    def test_session_manager_defaults_interactive_false(
        self, tmp_path, monkeypatch
    ) -> None:
        from backend.execution.utils import session_manager as sm_mod

        captured: dict[str, object] = {}

        def fake_create_shell_session(**kwargs):
            captured.update(kwargs)
            fake = MagicMock()
            fake.initialize.return_value = None
            return fake

        monkeypatch.setattr(sm_mod, 'create_shell_session', fake_create_shell_session)

        manager = sm_mod.SessionManager(
            work_dir=str(tmp_path),
            username='test',
            tool_registry=MagicMock(),
        )
        manager.create_session(session_id='default', cwd=str(tmp_path))
        assert captured.get('interactive') is False


# ---------------------------------------------------------------------------
# Live integration tests (spawn real shell via PTY primitive)
# ---------------------------------------------------------------------------


@requires_pty
class TestLivePtyShellSession:
    def _make(self, tmp_path) -> PtyInteractiveShellSession:
        session = PtyInteractiveShellSession(
            work_dir=str(tmp_path),
            username='test',
        )
        session.initialize()
        return session

    def test_initialize_and_close(self, tmp_path) -> None:
        session = self._make(tmp_path)
        assert session._initialized
        assert session._pty is not None
        session.close()
        assert session._closed
        assert session._pty is None

    def test_execute_produces_output_observation(self, tmp_path) -> None:
        session = self._make(tmp_path)
        try:
            marker = 'grinta-exec-round-trip'
            obs = session.execute(CmdRunAction(command=f'echo {marker}'))
            assert isinstance(obs, CmdOutputObservation)
            # Give the reader thread time if the echo hasn't drained yet.
            assert _wait_for(
                lambda: marker in session.read_output(),
                timeout=5.0,
            ), f'marker not observed; buffer={session.read_output()!r}'
        finally:
            session.close()

    def test_write_input_and_read_output_round_trip(self, tmp_path) -> None:
        session = self._make(tmp_path)
        try:
            marker = 'grinta-write-round-trip'
            if IS_WINDOWS:
                session.write_input(f'echo {marker}\r\n')
            else:
                session.write_input(f'echo {marker}\n')
            assert _wait_for(
                lambda: marker in session.read_output(),
                timeout=5.0,
            )
        finally:
            session.close()

    def test_control_sequence_alias_sent_to_pty(self, tmp_path) -> None:
        session = PtyInteractiveShellSession(work_dir=str(tmp_path))
        session._initialized = True
        fake_pty = MagicMock()
        session._pty = fake_pty
        session.write_input('C-c', is_control=True)
        fake_pty.send_control.assert_called_once_with('c')

    def test_resize_is_noop_without_pty(self, tmp_path) -> None:
        session = PtyInteractiveShellSession(work_dir=str(tmp_path))
        session.resize(rows=30, cols=100)  # must not raise


# ---------------------------------------------------------------------------
# Live bash + JSON PS1 (execute() exit / cwd)
# ---------------------------------------------------------------------------


@requires_pty
@requires_bash
@pytest.mark.skipif(
    IS_WINDOWS,
    reason='Git Bash + ConPTY often fails to emit parseable JSON PS1 in time; Linux/macOS CI covers this.',
)
class TestLiveBashPs1Execute:
    @staticmethod
    def _bash_argv() -> list[str]:
        p = shutil.which('bash')
        assert p
        return [p, '--norc', '--noprofile', '-i']

    def test_true_reports_exit_0(self, tmp_path) -> None:
        s = PtyInteractiveShellSession(
            work_dir=str(tmp_path),
            shell_argv=self._bash_argv(),
            enable_ps1_metadata=True,
        )
        s.initialize()
        try:
            assert s._ps1_ready
            obs = s.execute(CmdRunAction(command='true'))
            assert isinstance(obs, CmdOutputObservation)
            assert obs.metadata.exit_code == 0
        finally:
            s.close()

    def test_false_reports_exit_1(self, tmp_path) -> None:
        s = PtyInteractiveShellSession(
            work_dir=str(tmp_path),
            shell_argv=self._bash_argv(),
            enable_ps1_metadata=True,
        )
        s.initialize()
        try:
            assert s._ps1_ready
            obs = s.execute(CmdRunAction(command='false'))
            assert isinstance(obs, CmdOutputObservation)
            assert obs.metadata.exit_code == 1
        finally:
            s.close()
