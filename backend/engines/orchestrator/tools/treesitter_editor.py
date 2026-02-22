"""Compatibility wrapper for Tree-sitter editor utilities.

The canonical implementation lives in `backend.utils.treesitter_editor`.
Historically, orchestrator tools and tests import it from
`backend.engines.orchestrator.tools.treesitter_editor`, so we re-export the
public API here.

Tree-sitter is treated as a required dependency by the underlying
implementation.
"""

from __future__ import annotations

from backend.utils.treesitter_editor import (  # noqa: F401
    LANGUAGE_EXTENSIONS,
    TREE_SITTER_AVAILABLE,
    EditResult,
    SymbolLocation,
    TreeSitterEditor,
)

# `StructureEditor` is orchestrator-specific and implemented in this package.
from backend.engines.orchestrator.tools.structure_editor import (  # noqa: F401
    StructureEditor,
)
