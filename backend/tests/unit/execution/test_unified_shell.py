"""Tests for backend.execution.utils.unified_shell module.

Targets 23.1% coverage (78 statements) by testing BaseShellSession.
"""

from __future__ import annotations

import os
import sys
import types
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from backend.core.os_capabilities import OSCapabilities, override_os_capabilities
from backend.execution.utils.unified_shell import BaseShellSession, create_shell_session


def _force_os(request, *, windows: bool) -> None:
    """Override the global OS_CAPS for the duration of the calling test."""
    caps = OSCapabilities(
        is_windows=windows,
        is_posix=not windows,
        is_linux=not windows,
        is_macos=False,
        shell_kind='powershell' if windows else 'bash',
        supports_pty=not windows,
        signal_strategy='windows' if windows else 'posix',
        path_sep='\\' if windows else '/',
        default_python_exec='python' if windows else 'python3',
        sys_platform='win32' if windows else 'linux',
        os_name='nt' if windows else 'posix',
    )
    cm = override_os_capabilities(caps)
    cm.__enter__()
    request.addfinalizer(lambda: cm.__exit__(None, None, None))

# -----------------------------------------------------------
# Concrete stub
# -----------------------------------------------------------


class _ConcreteShell(BaseShellSession):
    def initialize(self):
        pass

    def execute(self, action: Any):
        pass


@pytest.fixture()
def shell(tmp_path) -> _ConcreteShell:
    return _ConcreteShell(work_dir=str(tmp_path))


# -----------------------------------------------------------
# __init__
# -----------------------------------------------------------


class TestBaseShellSessionInit:
    def test_work_dir_set(self, tmp_path):
        sh = _ConcreteShell(work_dir=str(tmp_path))
        assert os.path.isabs(sh.work_dir)
        assert sh._cwd == sh.work_dir

    def test_not_closed_or_initialized(self, shell):
        assert shell._closed is False
        assert shell._initialized is False

    def test_timeout_default(self, shell):
        assert shell.NO_CHANGE_TIMEOUT_SECONDS == 30

    def test_custom_timeout(self, tmp_path):
        sh = _ConcreteShell(work_dir=str(tmp_path), no_change_timeout_seconds=120)
        assert sh.NO_CHANGE_TIMEOUT_SECONDS == 120


# -----------------------------------------------------------
# cwd property
# -----------------------------------------------------------


class TestCwdProperty:
    def test_returns_current_dir(self, shell, tmp_path):
        assert shell.cwd == str(tmp_path.resolve())


# -----------------------------------------------------------
# _normalize_timeout
# -----------------------------------------------------------


class TestNormalizeTimeout:
    def test_none_returns_60(self, shell):
        assert shell._normalize_timeout(None) == 60

    def test_int_passthrough(self, shell):
        assert shell._normalize_timeout(30) == 30

    def test_string_converted(self, shell):
        assert shell._normalize_timeout('45') == 45

    def test_invalid_string_returns_60(self, shell):
        assert shell._normalize_timeout('bad') == 60

    def test_zero_returned(self, shell):
        assert shell._normalize_timeout(0) == 0


# -----------------------------------------------------------
# _prepare_command
# -----------------------------------------------------------


class TestPrepareCommand:
    def test_normal_command(self, shell):
        cmd, bg = shell._prepare_command('echo hello')
        assert cmd == 'echo hello'
        assert bg is False

    def test_background_command(self, shell):
        cmd, bg = shell._prepare_command('sleep 100 &')
        assert cmd == 'sleep 100'
        assert bg is True

    def test_strips_whitespace(self, shell):
        cmd, bg = shell._prepare_command('  echo hi  ')
        assert cmd == 'echo hi'
        assert bg is False

    def test_trailing_ampersand_stripped(self, shell):
        cmd, bg = shell._prepare_command('python server.py &')
        assert cmd == 'python server.py'
        assert bg is True


# -----------------------------------------------------------
# close
# -----------------------------------------------------------


class TestClose:
    def test_sets_closed(self, shell):
        shell.close()
        assert shell._closed is True


# -----------------------------------------------------------
# get_detected_server
# -----------------------------------------------------------


class TestGetDetectedServer:
    def test_default_returns_none(self, shell):
        assert shell.get_detected_server() is None


# -----------------------------------------------------------
# _update_cwd_from_output
# -----------------------------------------------------------


class TestUpdateCwdFromOutput:
    def test_updates_cwd_on_success(self, shell, tmp_path):
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=str(tmp_path) + '\n')
            shell._update_cwd_from_output(['pwd'])
        assert shell._cwd == str(tmp_path)

    def test_ignores_nonexistent_dir(self, shell):
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout='/nonexistent_xyz\n')
            original_cwd = shell._cwd
            shell._update_cwd_from_output(['pwd'])
        assert shell._cwd == original_cwd  # unchanged

    def test_ignores_subprocess_failure(self, shell):
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout='')
            original_cwd = shell._cwd
            shell._update_cwd_from_output(['pwd'])
        assert shell._cwd == original_cwd

    def test_handles_exception(self, shell):
        with patch('subprocess.run', side_effect=RuntimeError('whoops')):
            original_cwd = shell._cwd
            shell._update_cwd_from_output(['pwd'])
        assert shell._cwd == original_cwd


class _DummySession:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _DummyTools:
    def __init__(
        self,
        *,
        has_bash: bool,
        has_tmux: bool,
        has_powershell: bool = False,
        shell_type: str = 'bash',
    ):
        self.has_bash = has_bash
        self.has_tmux = has_tmux
        self.has_powershell = has_powershell
        self.shell_type = shell_type
        self.is_container_runtime = False
        self.is_wsl_runtime = False


class TestCreateShellSession:
    def test_unix_prefers_tmux_bash_session(self, tmp_path, monkeypatch, request):
        _force_os(request, windows=False)
        monkeypatch.setitem(
            sys.modules,
            'backend.execution.utils.bash',
            types.SimpleNamespace(BashSession=_DummySession),
        )

        tools = _DummyTools(has_bash=True, has_tmux=True)
        session = create_shell_session(
            work_dir=str(tmp_path),
            tools=tools,
            cancellation_service=MagicMock(),
        )
        assert isinstance(session, _DummySession)

    def test_sandboxed_local_non_interactive_avoids_tmux_session(
        self, tmp_path, monkeypatch, request
    ):
        _force_os(request, windows=False)
        monkeypatch.setitem(
            sys.modules,
            'backend.execution.utils.simple_bash',
            types.SimpleNamespace(SimpleBashSession=_DummySession),
        )

        tools = _DummyTools(has_bash=True, has_tmux=True)
        session = create_shell_session(
            work_dir=str(tmp_path),
            tools=tools,
            cancellation_service=MagicMock(),
            security_config=types.SimpleNamespace(execution_profile='sandboxed_local'),
        )
        assert isinstance(session, _DummySession)

    def test_sandboxed_local_allows_interactive_sessions(self, tmp_path, monkeypatch):
        class _FakePtyUnavailableError(RuntimeError):
            pass

        monkeypatch.setitem(
            sys.modules,
            'backend.execution.utils.pty_session',
            types.SimpleNamespace(PtyUnavailableError=_FakePtyUnavailableError),
        )
        monkeypatch.setitem(
            sys.modules,
            'backend.execution.utils.pty_shell_session',
            types.SimpleNamespace(PtyInteractiveShellSession=_DummySession),
        )

        tools = _DummyTools(has_bash=True, has_tmux=False)
        session = create_shell_session(
            work_dir=str(tmp_path),
            tools=tools,
            cancellation_service=MagicMock(),
            security_config=types.SimpleNamespace(execution_profile='sandboxed_local'),
            interactive=True,
        )

        assert isinstance(session, _DummySession)

    def test_sandboxed_local_interactive_falls_back_to_tmux_when_pty_unavailable(
        self, tmp_path, monkeypatch, request
    ):
        class _FakePtyUnavailableError(RuntimeError):
            pass

        class _RaisingPtySession:
            def __init__(self, **kwargs):
                raise _FakePtyUnavailableError('pty unavailable')

        _force_os(request, windows=False)
        monkeypatch.setitem(
            sys.modules,
            'backend.execution.utils.pty_session',
            types.SimpleNamespace(PtyUnavailableError=_FakePtyUnavailableError),
        )
        monkeypatch.setitem(
            sys.modules,
            'backend.execution.utils.pty_shell_session',
            types.SimpleNamespace(PtyInteractiveShellSession=_RaisingPtySession),
        )
        monkeypatch.setitem(
            sys.modules,
            'backend.execution.utils.bash',
            types.SimpleNamespace(BashSession=_DummySession),
        )

        tools = _DummyTools(has_bash=True, has_tmux=True)
        session = create_shell_session(
            work_dir=str(tmp_path),
            tools=tools,
            cancellation_service=MagicMock(),
            security_config=types.SimpleNamespace(execution_profile='sandboxed_local'),
            interactive=True,
        )

        assert isinstance(session, _DummySession)

    def test_unix_falls_back_to_simple_bash_without_tmux(self, tmp_path, monkeypatch, request):
        _force_os(request, windows=False)
        monkeypatch.setitem(
            sys.modules,
            'backend.execution.utils.simple_bash',
            types.SimpleNamespace(SimpleBashSession=_DummySession),
        )

        tools = _DummyTools(has_bash=True, has_tmux=False)
        session = create_shell_session(
            work_dir=str(tmp_path),
            tools=tools,
            cancellation_service=MagicMock(),
        )
        assert isinstance(session, _DummySession)

    def test_windows_prefers_powershell_when_available(self, tmp_path, monkeypatch, request):
        _force_os(request, windows=True)
        monkeypatch.setitem(
            sys.modules,
            'backend.execution.utils.windows_bash',
            types.SimpleNamespace(WindowsPowershellSession=_DummySession),
        )

        tools = _DummyTools(
            has_bash=True,
            has_tmux=False,
            has_powershell=True,
            shell_type='pwsh',
        )
        session = create_shell_session(
            work_dir=str(tmp_path),
            tools=tools,
            cancellation_service=MagicMock(),
        )
        assert isinstance(session, _DummySession)

    def test_windows_falls_back_to_bash_when_powershell_unavailable(
        self, tmp_path, monkeypatch, request
    ):
        _force_os(request, windows=True)
        monkeypatch.setitem(
            sys.modules,
            'backend.execution.utils.simple_bash',
            types.SimpleNamespace(SimpleBashSession=_DummySession),
        )

        tools = _DummyTools(
            has_bash=True,
            has_tmux=False,
            has_powershell=False,
            shell_type='cmd',
        )
        session = create_shell_session(
            work_dir=str(tmp_path),
            tools=tools,
            cancellation_service=MagicMock(),
        )
        assert isinstance(session, _DummySession)
