"""Tests for semantic_analyzer.find_references."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.engine.tools import semantic_analyzer as sa


def test_find_references_scans_simple_match(tmp_path: Path) -> None:
    src = tmp_path / 'a.py'
    src.write_text('def my_fn():\n    pass\nmy_fn()\n', encoding='utf-8')
    editor = MagicMock()
    editor.parse_file.return_value = (
        None,
        src.read_bytes(),
        None,
    )
    refs = sa.find_references(editor, 'my_fn', str(tmp_path))
    assert len(refs) >= 1
    assert any(r['path'] == str(src) for r in refs)


def test_find_references_skips_when_parse_returns_none(tmp_path: Path) -> None:
    src = tmp_path / 'b.py'
    src.write_text('x', encoding='utf-8')
    editor = MagicMock()
    editor.parse_file.return_value = None
    refs = sa.find_references(editor, 'sym', str(tmp_path))
    assert refs == []


def test_main_usage_error_exits(monkeypatch) -> None:
    monkeypatch.setattr('sys.argv', ['semantic_analyzer.py'])
    with pytest.raises(SystemExit):
        sa.main()
