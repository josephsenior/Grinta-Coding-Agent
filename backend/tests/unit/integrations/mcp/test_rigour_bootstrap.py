"""Tests for Rigour MCP workspace bootstrap (rigour.yml)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from backend.integrations.mcp.rigour_bootstrap import ensure_rigour_yml_for_mcp


def test_runs_cli_init_when_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        'backend.integrations.mcp.rigour_bootstrap.get_effective_workspace_root',
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        'backend.integrations.mcp.rigour_bootstrap.shutil.which',
        lambda _cmd: '/usr/bin/npx',
    )

    def _fake_run(cmd, **kwargs):
        assert cmd[:3] == ['/usr/bin/npx', '-y', '@rigour-labs/cli']
        assert cmd[3] == 'init'
        assert kwargs['cwd'] == tmp_path
        (tmp_path / 'rigour.yml').write_text(
            'version: 1\npreset: ui\n', encoding='utf-8'
        )
        return subprocess.CompletedProcess(cmd, 0, '', '')

    monkeypatch.setattr(
        'backend.integrations.mcp.rigour_bootstrap.subprocess.run', _fake_run
    )
    ensure_rigour_yml_for_mcp(None)
    assert (tmp_path / 'rigour.yml').read_text(
        encoding='utf-8'
    ) == 'version: 1\npreset: ui\n'


def test_does_not_write_yml_when_cli_init_fails(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        'backend.integrations.mcp.rigour_bootstrap.get_effective_workspace_root',
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        'backend.integrations.mcp.rigour_bootstrap.shutil.which',
        lambda _cmd: '/usr/bin/npx',
    )
    monkeypatch.setattr(
        'backend.integrations.mcp.rigour_bootstrap.subprocess.run',
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 1, '', 'network error'
        ),
    )
    ensure_rigour_yml_for_mcp(None)
    assert not (tmp_path / 'rigour.yml').exists()


def test_does_not_write_yml_when_npx_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        'backend.integrations.mcp.rigour_bootstrap.get_effective_workspace_root',
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        'backend.integrations.mcp.rigour_bootstrap.shutil.which',
        lambda _cmd: None,
    )
    ensure_rigour_yml_for_mcp(None)
    assert not (tmp_path / 'rigour.yml').exists()


def test_skips_when_rigour_yml_already_exists(tmp_path: Path, monkeypatch) -> None:
    existing = 'version: 1\ncustom: true\n'
    (tmp_path / 'rigour.yml').write_text(existing, encoding='utf-8')
    monkeypatch.setattr(
        'backend.integrations.mcp.rigour_bootstrap.get_effective_workspace_root',
        lambda: tmp_path,
    )

    def _should_not_run(*args, **kwargs):
        raise AssertionError(
            'subprocess.run should not be called when rigour.yml exists'
        )

    monkeypatch.setattr(
        'backend.integrations.mcp.rigour_bootstrap.subprocess.run', _should_not_run
    )
    ensure_rigour_yml_for_mcp(None)
    assert (tmp_path / 'rigour.yml').read_text(encoding='utf-8') == existing


def test_uses_rigour_cwd_from_env(tmp_path: Path, monkeypatch) -> None:
    ws = tmp_path / 'ws'
    ws.mkdir()
    monkeypatch.setattr(
        'backend.integrations.mcp.rigour_bootstrap.shutil.which',
        lambda _cmd: '/usr/bin/npx',
    )

    def _fake_run(cmd, **kwargs):
        assert kwargs['cwd'] == ws
        (ws / 'rigour.yml').write_text('version: 1\n', encoding='utf-8')
        return subprocess.CompletedProcess(cmd, 0, '', '')

    monkeypatch.setattr(
        'backend.integrations.mcp.rigour_bootstrap.subprocess.run', _fake_run
    )
    ensure_rigour_yml_for_mcp({'RIGOUR_CWD': str(ws)})
    assert (ws / 'rigour.yml').is_file()
    assert not (tmp_path / 'rigour.yml').exists()
