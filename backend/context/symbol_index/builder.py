"""Parse source files and extract symbols + imports for indexing."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.context.symbol_index.imports import downstream_import_paths
from backend.engine.tools._file_ops import (
    _SOURCE_SYMBOL_SUFFIXES,
    _candidate_from_location,
    _node_kind,
    _relative_display_path,
    _sha256_text,
)

_MAX_SYMBOLS_PER_FILE = 120


@dataclass(frozen=True)
class IndexedFile:
    path: str
    content_hash: str
    mtime_ns: int
    language: str
    symbols: tuple[dict[str, Any], ...]
    import_targets: tuple[str, ...]


def _language_for_suffix(suffix: str) -> str:
    return suffix.lstrip('.').lower() or 'unknown'


def normalize_workspace_path(path: str) -> str:
    return path.strip().replace('\\', '/').lstrip('./')


def _extract_symbols_via_ast(display_path: str, content: str) -> list[dict[str, Any]]:
    symbols: list[dict[str, Any]] = []
    try:
        tree = ast.parse(content)
    except (SyntaxError, ValueError):
        return symbols

    class StackVisitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.parent: str | None = None

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            if not node.name.startswith('_'):
                location = type(
                    '_Location',
                    (),
                    {
                        'symbol_name': node.name,
                        'node_type': 'class_definition',
                        'symbol_kind': 'class',
                        'parent_name': self.parent,
                        'line_start': node.lineno,
                        'line_end': node.end_lineno or node.lineno,
                    },
                )()
                symbols.append(
                    _candidate_from_location(location, content, display_path)
                )
            previous = self.parent
            self.parent = node.name
            self.generic_visit(node)
            self.parent = previous

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._visit_function(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._visit_function(node)

        def _visit_function(self, node: ast.AST) -> None:
            name = getattr(node, 'name', '')
            if not name or (name.startswith('_') and self.parent is None):
                return
            kind = 'method' if self.parent else 'function'
            location = type(
                '_Location',
                (),
                {
                    'symbol_name': name,
                    'node_type': 'function_definition',
                    'symbol_kind': kind,
                    'parent_name': self.parent,
                    'line_start': getattr(node, 'lineno', 0),
                    'line_end': getattr(node, 'end_lineno', None)
                    or getattr(node, 'lineno', 0),
                },
            )()
            symbols.append(_candidate_from_location(location, content, display_path))

    StackVisitor().visit(tree)
    return symbols[:_MAX_SYMBOLS_PER_FILE]


def _extract_symbols_via_treesitter(
    path: Path, display_path: str
) -> list[dict[str, Any]]:
    from backend.utils.treesitter.treesitter_editor import TreeSitterEditor

    editor = TreeSitterEditor()
    parse_result = editor.parse_file(str(path), use_cache=False)
    if not parse_result:
        return []

    tree, file_bytes, _language = parse_result
    content = file_bytes.decode('utf-8', errors='replace')

    class_types = {
        'class_definition',
        'class_declaration',
        'class_specifier',
    }
    function_types = {
        'function_definition',
        'function_declaration',
        'function',
        'method_definition',
        'method_declaration',
        'constructor_declaration',
        'function_item',
        'method',
        'singleton_method',
    }
    target_types = class_types | function_types
    symbols: list[dict[str, Any]] = []

    def visit(node: Any, parent_name: str | None = None) -> None:
        next_parent = parent_name
        if node.type in target_types:
            name_node = editor.get_name_node(node)
            if name_node is not None:
                name = file_bytes[name_node.start_byte : name_node.end_byte].decode(
                    'utf-8', errors='replace'
                )
                if name.startswith('_') and parent_name is None:
                    return
                base_kind = _node_kind(str(node.type))
                kind = (
                    'method' if parent_name and base_kind == 'function' else base_kind
                )
                location = type(
                    '_Location',
                    (),
                    {
                        'symbol_name': name,
                        'node_type': node.type,
                        'symbol_kind': kind,
                        'parent_name': parent_name,
                        'line_start': node.start_point[0] + 1,
                        'line_end': node.end_point[0] + 1,
                    },
                )()
                symbols.append(
                    _candidate_from_location(location, content, display_path)
                )
                if kind == 'class':
                    next_parent = name
        for child in getattr(node, 'children', []) or []:
            visit(child, next_parent)

    visit(tree.root_node)
    return symbols


def extract_symbols_from_file(path: Path) -> list[dict[str, Any]]:
    """Extract public class/function symbols from a source file."""
    if path.suffix.lower() not in _SOURCE_SYMBOL_SUFFIXES:
        return []

    try:
        content = path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return []

    display_path = normalize_workspace_path(_relative_display_path(path))
    symbols = _extract_symbols_via_treesitter(path, display_path)
    if not symbols and path.suffix.lower() == '.py':
        symbols = _extract_symbols_via_ast(display_path, content)
    return symbols[:_MAX_SYMBOLS_PER_FILE]


def build_indexed_file(path: Path, workspace_root: Path) -> IndexedFile | None:
    """Parse ``path`` and return index payload, or None when unsupported."""
    if not path.is_file():
        return None
    if path.suffix.lower() not in _SOURCE_SYMBOL_SUFFIXES:
        return None

    try:
        stat = path.stat()
        content = path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return None

    rel = normalize_workspace_path(_relative_display_path(path))
    imports = tuple(
        normalize_workspace_path(target)
        for target in downstream_import_paths(rel, str(workspace_root))
        if normalize_workspace_path(target) != rel
    )
    return IndexedFile(
        path=rel,
        content_hash=_sha256_text(content),
        mtime_ns=stat.st_mtime_ns,
        language=_language_for_suffix(path.suffix),
        symbols=tuple(extract_symbols_from_file(path)),
        import_targets=imports,
    )


def is_source_index_candidate(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in _SOURCE_SYMBOL_SUFFIXES
