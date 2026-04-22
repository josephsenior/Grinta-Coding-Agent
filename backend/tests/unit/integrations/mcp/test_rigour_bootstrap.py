"""Tests for Rigour MCP workspace bootstrap (minimal rigour.yml)."""

from __future__ import annotations

from pathlib import Path

from backend.integrations.mcp.rigour_bootstrap import ensure_minimal_rigour_yml_for_mcp


def test_writes_minimal_rigour_yml_when_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        'backend.integrations.mcp.rigour_bootstrap.get_effective_workspace_root',
        lambda: tmp_path,
    )
    ensure_minimal_rigour_yml_for_mcp(None)
    text = (tmp_path / 'rigour.yml').read_text(encoding='utf-8')
    assert 'version: 1' in text
    assert 'preset: api' in text


def test_skips_when_rigour_yml_already_exists(tmp_path: Path, monkeypatch) -> None:
    existing = 'version: 1\ncustom: true\n'
    (tmp_path / 'rigour.yml').write_text(existing, encoding='utf-8')
    monkeypatch.setattr(
        'backend.integrations.mcp.rigour_bootstrap.get_effective_workspace_root',
        lambda: tmp_path,
    )
    ensure_minimal_rigour_yml_for_mcp(None)
    assert (tmp_path / 'rigour.yml').read_text(encoding='utf-8') == existing


def test_uses_rigour_cwd_from_env(tmp_path: Path) -> None:
    ws = tmp_path / 'ws'
    ws.mkdir()
    ensure_minimal_rigour_yml_for_mcp({'RIGOUR_CWD': str(ws)})
    assert (ws / 'rigour.yml').is_file()
    assert not (tmp_path / 'rigour.yml').exists()
