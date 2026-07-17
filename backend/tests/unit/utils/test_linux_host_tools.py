from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

from backend.utils import linux_host_tools as lht


def test_is_linux_host_on_linux():
    with patch.object(lht.sys, 'platform', 'linux'):
        assert lht.is_linux_host() is True


def test_is_linux_host_on_windows():
    with patch.object(lht.sys, 'platform', 'win32'):
        assert lht.is_linux_host() is False


def test_ensure_skips_non_linux():
    with patch.object(lht.sys, 'platform', 'darwin'):
        result = lht.ensure_linux_host_tools()
    assert result.attempted_install is False
    assert result.message == 'not a Linux host'


def test_ensure_tmux_already_present():
    with (
        patch.object(lht.sys, 'platform', 'linux'),
        patch.object(lht.shutil, 'which', return_value='/usr/bin/tmux'),
        patch.object(lht, '_has_libtmux', return_value=True),
    ):
        result = lht.ensure_linux_host_tools()
    assert result.tmux_installed is True
    assert result.attempted_install is False


def test_ensure_installs_tmux_via_apt():
    which_calls = {'tmux': 0}

    def fake_which(name: str):
        if name == 'apt-get':
            return '/usr/bin/apt-get'
        if name == 'tmux':
            which_calls['tmux'] += 1
            return '/usr/bin/tmux' if which_calls['tmux'] > 1 else None
        return None

    with (
        patch.object(lht.sys, 'platform', 'linux'),
        patch.object(lht.shutil, 'which', side_effect=fake_which),
        patch.object(lht, '_has_libtmux', return_value=True),
        patch.object(lht, '_run_install', return_value=True) as run_install,
    ):
        result = lht.ensure_linux_host_tools()

    assert result.tmux_installed is True
    assert result.attempted_install is True
    run_install.assert_called_once()


def test_ensure_respects_skip_env():
    with (
        patch.dict('os.environ', {'GRINTA_SKIP_HOST_TOOL_INSTALL': '1'}),
        patch.object(lht.sys, 'platform', 'linux'),
        patch.object(lht.shutil, 'which', return_value=None),
        patch.object(lht, '_has_libtmux', return_value=True),
        patch.object(lht, '_run_install') as run_install,
    ):
        result = lht.ensure_linux_host_tools()

    assert result.tmux_installed is False
    assert result.attempted_install is False
    run_install.assert_not_called()


def test_detect_linux_package_manager_all_variants() -> None:
    # Test dnf
    with patch.object(lht.shutil, 'which', side_effect=lambda name: '/bin/dnf' if name == 'dnf' else None):
        assert lht._detect_linux_package_manager() == 'dnf'

    # Test yum
    with patch.object(lht.shutil, 'which', side_effect=lambda name: '/bin/yum' if name == 'yum' else None):
        assert lht._detect_linux_package_manager() == 'yum'

    # Test apk
    with patch.object(lht.shutil, 'which', side_effect=lambda name: '/bin/apk' if name == 'apk' else None):
        assert lht._detect_linux_package_manager() == 'apk'

    # Test pacman
    with patch.object(lht.shutil, 'which', side_effect=lambda name: '/bin/pacman' if name == 'pacman' else None):
        assert lht._detect_linux_package_manager() == 'pacman'

    # Test zypper
    with patch.object(lht.shutil, 'which', side_effect=lambda name: '/bin/zypper' if name == 'zypper' else None):
        assert lht._detect_linux_package_manager() == 'zypper'

    # Test unsupported
    with patch.object(lht.shutil, 'which', return_value=None):
        assert lht._detect_linux_package_manager() is None


def test_install_command_variants() -> None:
    assert len(lht._install_command_variants('apt')) == 3
    assert len(lht._install_command_variants('dnf')) == 3
    assert len(lht._install_command_variants('yum')) == 3
    assert len(lht._install_command_variants('apk')) == 3
    assert len(lht._install_command_variants('pacman')) == 3
    assert len(lht._install_command_variants('zypper')) == 3
    assert lht._install_command_variants('unknown_pm') == []


def test_run_install_scenarios() -> None:
    # 1. Success
    mock_res_success = MagicMock(returncode=0)
    with patch('subprocess.run', return_value=mock_res_success):
        assert lht._run_install(['echo', 'hi']) is True

    # 2. Failure with stderr/stdout output
    mock_res_fail = MagicMock(returncode=1, stderr='error log', stdout='')
    with patch('subprocess.run', return_value=mock_res_fail):
        assert lht._run_install(['echo', 'hi']) is False

    # 3. TimeoutExpired exception
    with patch('subprocess.run', side_effect=subprocess.TimeoutExpired(['cmd'], 300)):
        assert lht._run_install(['echo', 'hi']) is False

    # 4. OSError exception
    with patch('subprocess.run', side_effect=OSError("binary not found")):
        assert lht._run_install(['echo', 'hi']) is False


def test_ensure_linux_host_tools_unsupported_pm() -> None:
    with (
        patch.object(lht.sys, 'platform', 'linux'),
        patch.object(lht.shutil, 'which', return_value=None),
        patch.object(lht, '_has_libtmux', return_value=False),  # also missing libtmux
    ):
        result = lht.ensure_linux_host_tools()
        assert result.tmux_installed is False
        assert result.libtmux_available is False
        assert result.message == 'tmux missing; unsupported package manager'


def test_ensure_linux_host_tools_install_failed() -> None:
    # Simulate dnf package manager, interactive install allowed, but installer fails
    with (
        patch.object(lht.sys, 'platform', 'linux'),
        patch.object(lht.shutil, 'which', side_effect=lambda name: '/bin/dnf' if name == 'dnf' else None),
        patch.object(lht, '_has_libtmux', return_value=True),
        patch.object(lht, '_interactive_install_allowed', return_value=True),
        patch.object(lht, '_run_install', return_value=False),
    ):
        result = lht.ensure_linux_host_tools()
        assert result.tmux_installed is False
        assert result.attempted_install is True
        assert 'automatic install failed' in result.message


def test_interactive_install_allowed() -> None:
    # Check returns True only if both stdin/stdout are tty
    with patch.object(lht.sys.stdin, 'isatty', return_value=True), \
         patch.object(lht.sys.stdout, 'isatty', return_value=True):
        assert lht._interactive_install_allowed() is True

    with patch.object(lht.sys.stdin, 'isatty', return_value=False):
        assert lht._interactive_install_allowed() is False

