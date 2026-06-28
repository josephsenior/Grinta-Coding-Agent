"""Tests for LSP auto-install logic."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend.utils.lsp import lsp_client as lc
from backend.utils.lsp.lsp_installer import (
    install_server,
    is_auto_install_enabled,
    reset_install_cache,
    was_installed,
)


def test_is_auto_install_enabled_by_default() -> None:
    with patch.dict('os.environ', {}, clear=False):
        import os

        os.environ.pop('GRINTA_LSP_AUTO_INSTALL', None)
        assert is_auto_install_enabled() is True


def test_is_auto_install_disabled_via_env() -> None:
    with patch.dict('os.environ', {'GRINTA_LSP_AUTO_INSTALL': '0'}):
        assert is_auto_install_enabled() is False


def test_install_server_success() -> None:
    reset_install_cache()
    with (
        patch(
            'backend.utils.lsp.lsp_installer.which_normalized',
            return_value='/usr/bin/npm',
        ),
        patch('subprocess.run', return_value=MagicMock(returncode=0, stderr=b'')),
    ):
        result = install_server(
            'test-server',
            ('npm', 'install', '-g', 'test-server'),
            'npm',
        )
    assert result is True
    assert was_installed('test-server')


def test_install_server_skips_when_already_installed() -> None:
    reset_install_cache()
    with (
        patch(
            'backend.utils.lsp.lsp_installer.which_normalized',
            return_value='/usr/bin/npm',
        ),
        patch('subprocess.run', return_value=MagicMock(returncode=0, stderr=b'')),
    ):
        install_server('test-server', ('npm', 'install', '-g', 'x'), 'npm')
    with patch('subprocess.run', side_effect=AssertionError('should not run')) as run:
        install_server('test-server', ('npm', 'install', '-g', 'x'), 'npm')
    run.assert_not_called()
    assert was_installed('test-server')


def test_install_server_no_install_command() -> None:
    reset_install_cache()
    result = install_server('binary-only-server', None, 'binary')
    assert result is False


def test_install_server_missing_prereq() -> None:
    reset_install_cache()
    with patch('backend.utils.lsp.lsp_installer.which_normalized', return_value=None):
        result = install_server('go-server', ('go', 'install', 'x'), 'go')
    assert result is False


def test_install_server_failed_does_not_retry() -> None:
    reset_install_cache()
    with patch(
        'subprocess.run',
        return_value=MagicMock(returncode=1, stderr=b'permission denied'),
    ):
        result1 = install_server('failing-server', ('npm', 'install', '-g', 'x'), 'npm')
    assert result1 is False
    with patch('subprocess.run', side_effect=AssertionError('should not retry')) as run:
        result2 = install_server('failing-server', ('npm', 'install', '-g', 'x'), 'npm')
    run.assert_not_called()
    assert result2 is False


def test_install_server_timeout() -> None:
    reset_install_cache()
    with patch('subprocess.run', side_effect=subprocess.TimeoutExpired('cmd', 1)):
        result = install_server('slow-server', ('npm', 'install', '-g', 'x'), 'npm')
    assert result is False


def test_get_context_triggers_auto_install(tmp_path: Path) -> None:
    """When the server is missing and auto-install is on, LspClient tries to install."""
    reset_install_cache()
    py_file = tmp_path / 'app.py'
    py_file.write_text('x = 1\n', encoding='utf-8')
    (tmp_path / 'pyproject.toml').write_text('[project]\nname="x"\n', encoding='utf-8')

    client = lc.LspClient()
    fake_ctx = lc.LspFileContext(
        server_name='pyright-langserver',
        command=('pyright-langserver', '--stdio'),
        language_id='python',
        workspace_root=tmp_path,
    )
    with (
        patch(
            'backend.utils.lsp.lsp_client.lsp_context_for_file',
            side_effect=[None, fake_ctx],
        ),
        patch(
            'backend.utils.lsp.lsp_installer.is_auto_install_enabled',
            return_value=True,
        ),
        patch(
            'backend.utils.lsp.lsp_installer.install_server',
            return_value=True,
        ),
        patch('backend.utils.runtime_detect.reset_detection_cache'),
    ):
        ctx = client._get_context(str(py_file))  # noqa: SLF001
    assert ctx is not None
    assert ctx.server_name == 'pyright-langserver'


def test_get_context_skips_auto_install_when_disabled(tmp_path: Path) -> None:
    """When auto-install is off, _get_context returns None without trying."""
    reset_install_cache()
    py_file = tmp_path / 'app.py'
    py_file.write_text('x = 1\n', encoding='utf-8')

    client = lc.LspClient()
    with (
        patch(
            'backend.utils.lsp.lsp_client.lsp_context_for_file',
            return_value=None,
        ),
        patch(
            'backend.utils.lsp.lsp_installer.is_auto_install_enabled',
            return_value=False,
        ),
        patch(
            'backend.utils.lsp.lsp_installer.install_server',
            side_effect=AssertionError('should not install'),
        ),
    ):
        ctx = client._get_context(str(py_file))  # noqa: SLF001
    assert ctx is None
