"""Unit tests for runtime_detect probe ladder."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

from backend.utils.runtime_detect import (
    DetectedTool,
    LSP_SERVERS,
    ToolSpec,
    _detect_all,
    _probe,
    detect_lsp_servers,
    reset_detection_cache,
)


def _spec(**kwargs) -> ToolSpec:
    defaults = {
        'name': 'tool',
        'language': 'python',
        'extensions': ('.py',),
        'command': ('missing-binary',),
        'probe': None,
        'python_module': None,
    }
    defaults.update(kwargs)
    return ToolSpec(**defaults)


def test_probe_finds_executable_on_path() -> None:
    spec = _spec(command=('rg', '--help'))
    with patch('shutil.which', return_value='/usr/bin/rg'):
        result = _probe(spec)
    assert result.available is True
    assert result.resolved_command[0] == '/usr/bin/rg'


def test_probe_uses_python_module_import() -> None:
    spec = _spec(
        command=('python', '-m', 'json'),
        python_module='json',
    )
    with (
        patch('shutil.which', return_value=None),
        patch('subprocess.run', return_value=MagicMock(returncode=0)),
    ):
        result = _probe(spec)
    assert result.available is True
    assert 'json' in result.detail


def test_probe_runs_explicit_probe_command() -> None:
    spec = _spec(command=('missing-head',), probe=('probe-cmd', '--version'))
    with (
        patch(
            'shutil.which',
            side_effect=lambda cmd: '/bin/probe-cmd' if cmd == 'probe-cmd' else None,
        ),
        patch('subprocess.run', return_value=MagicMock(returncode=0)) as run,
    ):
        result = _probe(spec)
    assert result.available is True
    assert run.called
    assert 'probe command succeeded' in result.detail


def test_probe_returns_unavailable_when_not_found() -> None:
    spec = _spec(command=('definitely-missing-tool-xyz',))
    with patch('shutil.which', return_value=None):
        result = _probe(spec)
    assert result.available is False
    assert result.detail == 'not found'


def test_probe_handles_subprocess_timeout() -> None:
    spec = _spec(
        command=('missing-head',),
        probe=('probe-cmd', '--version'),
    )
    with (
        patch(
            'shutil.which',
            side_effect=lambda cmd: '/bin/probe-cmd' if cmd == 'probe-cmd' else None,
        ),
        patch('subprocess.run', side_effect=subprocess.TimeoutExpired('tool', 1)),
    ):
        result = _probe(spec)
    assert result.available is False


def test_detect_all_catches_probe_exceptions() -> None:
    broken = _spec(name='broken')
    with patch('backend.utils.runtime_detect._probe', side_effect=RuntimeError('boom')):
        results = _detect_all([broken])
    assert results['broken'].available is False
    assert 'boom' in results['broken'].detail


def test_detect_lsp_servers_uses_cache() -> None:
    reset_detection_cache()
    fake = DetectedTool(spec=LSP_SERVERS[0], available=True, detail='ok')
    with patch('backend.utils.runtime_detect._detect_all', return_value={'pylsp': fake}) as detect:
        first = detect_lsp_servers()
        second = detect_lsp_servers()
    assert detect.call_count == 1
    assert first is second
