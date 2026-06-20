"""Backward-compatible re-exports for tree-sitter editor symbols."""

from backend.engine.tools.structure_editor import StructureEditor
from backend.utils.treesitter.treesitter_editor import (
    LANGUAGE_EXTENSIONS,
    TREE_SITTER_AVAILABLE,
    EditResult,
    SymbolLocation,
    TreeSitterEditor,
)

__all__ = [
    'EditResult',
    'LANGUAGE_EXTENSIONS',
    'StructureEditor',
    'SymbolLocation',
    'TREE_SITTER_AVAILABLE',
    'TreeSitterEditor',
]
