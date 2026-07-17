"""Unit tests for Tree-sitter lightweight editor types."""

from __future__ import annotations

from backend.utils.treesitter._tse_types import (
    AmbiguousSymbolError,
    EditResult,
    SymbolLocation,
)


def test_symbol_location() -> None:
    loc = SymbolLocation(
        file_path="main.py",
        line_start=5,
        line_end=8,
        byte_start=50,
        byte_end=80,
        node_type="function_definition",
        symbol_name="greet",
        parent_name="Person",
    )
    assert loc.file_path == "main.py"
    assert loc.line_start == 5
    assert loc.line_end == 8
    assert loc.byte_start == 50
    assert loc.byte_end == 80
    assert loc.node_type == "function_definition"
    assert loc.symbol_name == "greet"
    assert loc.parent_name == "Person"


def test_ambiguous_symbol_error() -> None:
    loc1 = SymbolLocation(
        file_path="main.py",
        line_start=10,
        line_end=12,
        byte_start=100,
        byte_end=120,
        node_type="function_definition",
        symbol_name="foo",
    )
    loc2 = SymbolLocation(
        file_path="main.py",
        line_start=20,
        line_end=22,
        byte_start=200,
        byte_end=220,
        node_type="function_definition",
        symbol_name="foo",
    )
    
    err = AmbiguousSymbolError("foo", [loc1, loc2])
    assert err.symbol_name == "foo"
    assert len(err.matches) == 2
    assert "Found 2 'foo' symbols: lines 10, 20" in str(err)


def test_edit_result() -> None:
    res = EditResult(
        success=True,
        message="edited",
        modified_code="new_code",
        lines_changed=2,
        syntax_valid=True,
        original_code="old_code",
    )
    assert res.success is True
    assert res.message == "edited"
    assert res.modified_code == "new_code"
    assert res.lines_changed == 2
    assert res.syntax_valid is True
    assert res.original_code == "old_code"
