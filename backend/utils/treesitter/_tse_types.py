"""Public dataclasses and exceptions exposed by the tree-sitter editor.

Kept in a dedicated module so callers (and the orchestrator re-export shim)
can import lightweight types without pulling in tree-sitter or the editor
class itself.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SymbolLocation:
    """Universal symbol location (works for any language)."""

    file_path: str
    line_start: int
    line_end: int
    byte_start: int
    byte_end: int
    node_type: str  # "function_definition", "class_declaration", etc.
    symbol_name: str
    parent_name: str | None = None


class AmbiguousSymbolError(Exception):
    """Raised when multiple symbols match the search criteria."""

    def __init__(self, symbol_name: str, matches: list[SymbolLocation]):
        self.symbol_name = symbol_name
        self.matches = matches
        match_lines = ', '.join(str(m.line_start) for m in matches)
        super().__init__(
            f"Found {len(matches)} '{symbol_name}' symbols: lines {match_lines}. "
            f"Use 'line_number' parameter to disambiguate."
        )


@dataclass
class EditResult:
    """Result of an edit operation."""

    success: bool
    message: str
    modified_code: str | None = None
    lines_changed: int = 0
    syntax_valid: bool = True
    original_code: str | None = None
