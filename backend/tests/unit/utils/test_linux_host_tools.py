from __future__ import annotations

from unittest.mock import patch

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
