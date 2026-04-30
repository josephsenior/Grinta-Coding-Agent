"""Tests for read_symbol_definition helpers (no full tree-sitter graph required)."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.engine.tools import read_symbol as rs


def test_create_read_symbol_definition_tool_shape() -> None:
    tool = rs.create_read_symbol_definition_tool()
    assert tool['function']['name'] == rs.READ_SYMBOL_DEFINITION_TOOL_NAME
    assert 'entity_names' in tool['function']['parameters']['properties']


def test_read_text_truncates_when_over_limit(tmp_path: Path) -> None:
    p = tmp_path / 'big.bin'
    p.write_bytes(b'x' * 250_000)
    text = rs._read_text(str(p), max_bytes=1000)
    assert 'truncated' in text.lower()
    assert len(text) <= 2000


def test_extract_symbol_empty_path() -> None:
    out = rs._extract_symbol(':')
    assert out.get('error') == 'empty path'


def test_extract_symbol_file_not_found(tmp_path: Path) -> None:
    missing = tmp_path / 'nope.py'
    out = rs._extract_symbol(str(missing))
    assert 'not found' in out.get('error', '').lower()


def test_extract_symbol_whole_file_without_symbol(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = tmp_path / 'only.py'
    f.write_text('# hello\n', encoding='utf-8')
    monkeypatch.chdir(tmp_path)
    out = rs._extract_symbol('only.py')
    assert out.get('kind') == 'file'
    assert 'hello' in out.get('content', '')


def test_build_read_symbol_definition_action_serializes_results() -> None:
    act = rs.build_read_symbol_definition_action({'entity_names': ['missing.py:nope']})
    assert 'READ_SYMBOL_DEFINITION' in act.thought
    assert 'results' in act.thought
