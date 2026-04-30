"""Ensure the orchestrator shim re-exports tree-sitter editor symbols."""

from __future__ import annotations

import backend.engine.tools.treesitter_editor as shim


def test_treesitter_editor_shim_exports_structure_editor_and_utils() -> None:
    assert shim.StructureEditor is not None
    assert shim.TreeSitterEditor is not None
    assert isinstance(shim.LANGUAGE_EXTENSIONS, dict)
    assert isinstance(shim.TREE_SITTER_AVAILABLE, bool)
    assert shim.EditResult is not None
    assert shim.SymbolLocation is not None
