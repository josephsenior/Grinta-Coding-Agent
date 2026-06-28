"""Tests for Rigour MCP workspace bootstrap (rigour.yml)."""

from __future__ import annotations

from pathlib import Path

from backend.integrations.mcp.rigour_bootstrap import (
    MINIMAL_RIGOUR_YML,
    ensure_rigour_yml_for_mcp,
    write_minimal_rigour_yml,
)


def test_writes_minimal_stub_when_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        'backend.integrations.mcp.rigour_bootstrap.get_effective_workspace_root',
        lambda: tmp_path,
    )
    ensure_rigour_yml_for_mcp(None)
    assert (tmp_path / 'rigour.yml').read_text(encoding='utf-8') == MINIMAL_RIGOUR_YML


def test_write_minimal_rigour_yml_is_idempotent(tmp_path: Path) -> None:
    assert write_minimal_rigour_yml(tmp_path) is True
    first = (tmp_path / 'rigour.yml').read_text(encoding='utf-8')
    assert write_minimal_rigour_yml(tmp_path) is True
    assert (tmp_path / 'rigour.yml').read_text(encoding='utf-8') == first


def test_skips_when_rigour_yml_already_exists(tmp_path: Path, monkeypatch) -> None:
    existing = 'version: 1\ncustom: true\n'
    (tmp_path / 'rigour.yml').write_text(existing, encoding='utf-8')
    monkeypatch.setattr(
        'backend.integrations.mcp.rigour_bootstrap.get_effective_workspace_root',
        lambda: tmp_path,
    )
    ensure_rigour_yml_for_mcp(None)
    assert (tmp_path / 'rigour.yml').read_text(encoding='utf-8') == existing


def test_uses_rigour_cwd_from_env(tmp_path: Path) -> None:
    ws = tmp_path / 'ws'
    ws.mkdir()
    ensure_rigour_yml_for_mcp({'RIGOUR_CWD': str(ws)})
    assert (ws / 'rigour.yml').read_text(encoding='utf-8') == MINIMAL_RIGOUR_YML
    assert not (tmp_path / 'rigour.yml').exists()
