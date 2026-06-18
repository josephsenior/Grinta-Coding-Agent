"""File and symbol read helpers used by function-calling tool handlers.

Pure code motion: split from ``backend.engine.function_calling`` to keep
that module under the 40 KB file-size cap. No logic changes.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from backend.core.errors import FunctionCallValidationError


def _workspace_root() -> Path:
    try:
        from backend.core.workspace_resolution import require_effective_workspace_root

        return Path(require_effective_workspace_root()).resolve()
    except Exception:
        return Path.cwd().resolve()


def _safe_workspace_path(path: str, *, must_exist: bool = False) -> Path:
    from backend.core.type_safety.path_validation import SafePath

    return SafePath.validate(
        path,
        workspace_root=_workspace_root(),
        must_exist=must_exist,
        must_be_relative=True,
    ).path


def _relative_display_path(path: Path) -> str:
    root = _workspace_root()
    try:
        return str(path.resolve().relative_to(root))
    except ValueError:
        return str(path)


def _sha256_text(content: str) -> str:
    import hashlib

    return hashlib.sha256(content.encode('utf-8')).hexdigest()


def _read_text_for_tool(path: Path) -> str:
    return path.read_text(encoding='utf-8')


def _guard_content_arguments(arguments: Mapping[str, Any]) -> None:
    from backend.core.content_escape_repair import validate_content_payloads

    validate_content_payloads(dict(arguments))


def _symbol_id(path: str, name: str, start_line: int, end_line: int) -> str:
    return f'{path}:{start_line}-{end_line}:{name}'


def _symbol_preview(content: str, start_line: int, end_line: int) -> str:
    lines = content.splitlines()
    if not lines:
        return ''
    selected = lines[start_line - 1 : min(end_line, start_line + 2)]
    return '\n'.join(selected)[:240]


def _candidate_from_location(
    location: Any, content: str, display_path: str
) -> dict[str, Any]:
    name = str(getattr(location, 'symbol_name', '') or '')
    parent = getattr(location, 'parent_name', None)
    start_line = int(getattr(location, 'line_start', 0) or 0)
    end_line = int(getattr(location, 'line_end', 0) or 0)
    kind = getattr(location, 'node_type', None)
    symbol_kind = str(getattr(location, 'symbol_kind', '') or '') or _node_kind(
        str(kind or '')
    )
    qualified_name = f'{parent}.{name}' if parent else name
    preview = _symbol_preview(content, start_line, end_line)
    return {
        'symbol_id': _symbol_id(display_path, name, start_line, end_line),
        'name': name,
        'qualified_name': qualified_name,
        'kind': kind,
        'symbol_kind': symbol_kind,
        'parent': parent,
        'path': display_path,
        'start_line': start_line,
        'end_line': end_line,
        'signature': preview,
        'preview': preview,
    }


_SOURCE_SYMBOL_SUFFIXES: frozenset[str] = frozenset(
    {'.py', '.js', '.jsx', '.ts', '.tsx', '.go', '.rs', '.java', '.rb', '.php'}
)
_SKIP_SYMBOL_SEARCH_PARTS: frozenset[str] = frozenset(
    {
        '.git',
        '.hg',
        '.svn',
        '.venv',
        'venv',
        'node_modules',
        '__pycache__',
        '.pytest_cache',
    }
)


def _node_kind(node_type: str) -> str:
    if 'class' in node_type:
        return 'class'
    if 'method' in node_type:
        return 'method'
    return 'function'


def _find_symbol_candidates_in_file(
    path: Path,
    query: str,
    *,
    symbol_kind: str | None = None,
    include_private: bool = False,
) -> list[dict[str, Any]]:
    from backend.utils.treesitter_editor import TreeSitterEditor

    editor = TreeSitterEditor()
    parse_result = editor.parse_file(str(path), use_cache=False)
    if not parse_result:
        return []
    tree, file_bytes, language = parse_result
    content = file_bytes.decode('utf-8', errors='replace')
    display_path = _relative_display_path(path)
    query_lower = query.lower()
    kind_filter = (symbol_kind or '').strip().lower()
    candidates: list[dict[str, Any]] = []

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

    def visit(node: Any, parent_name: str | None = None) -> None:
        next_parent = parent_name
        if node.type in target_types:
            name_node = editor.get_name_node(node)
            if name_node is not None:
                name = file_bytes[name_node.start_byte : name_node.end_byte].decode(
                    'utf-8', errors='replace'
                )
                base_kind = _node_kind(str(node.type))
                kind = (
                    'method' if parent_name and base_kind == 'function' else base_kind
                )
                if (
                    query_lower in name.lower()
                    and (include_private or not name.startswith('_'))
                    and (not kind_filter or kind == kind_filter)
                ):
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
                    candidates.append(
                        _candidate_from_location(location, content, display_path)
                    )
                if kind == 'class':
                    next_parent = name
        for child in getattr(node, 'children', []) or []:
            visit(child, next_parent)

    visit(tree.root_node)
    return candidates


def _candidate_paths_for_symbol_search(raw_path: str | None = None) -> list[Path]:
    if raw_path:
        return [_safe_workspace_path(raw_path, must_exist=True)]

    root = _workspace_root()
    paths: list[Path] = []
    for path in root.rglob('*'):
        if len(paths) >= 200:
            break
        if not path.is_file():
            continue
        if path.suffix.lower() not in _SOURCE_SYMBOL_SUFFIXES:
            continue
        if any(part in _SKIP_SYMBOL_SEARCH_PARTS for part in path.parts):
            continue
        paths.append(path)
    return paths


def _find_symbol_candidates(
    query: str,
    *,
    path: str | None = None,
    symbol_kind: str | None = None,
    include_private: bool = False,
) -> list[dict[str, Any]]:
    lookup_query = query.rsplit('.', 1)[-1]
    candidates: list[dict[str, Any]] = []
    for candidate_path in _candidate_paths_for_symbol_search(path):
        candidates.extend(
            _find_symbol_candidates_in_file(
                candidate_path,
                lookup_query,
                symbol_kind=symbol_kind,
                include_private=include_private,
            )
        )
    if '.' in query:
        query_lower = query.lower()
        candidates = [
            candidate
            for candidate in candidates
            if query_lower in str(candidate.get('qualified_name') or '').lower()
        ]
    return candidates


def _parse_symbol_id(symbol_id: str) -> tuple[str, str, int, int]:
    try:
        raw_path, range_part, raw_name = symbol_id.rsplit(':', 2)
        start_raw, _, end_raw = range_part.partition('-')
        start_line = int(start_raw)
        end_line = int(end_raw)
    except Exception as exc:
        raise FunctionCallValidationError(
            f'Invalid symbol_id {symbol_id!r}; use an id returned by find_symbols or read(type="symbols").'
        ) from exc
    if not raw_path or not raw_name or start_line < 1 or end_line < start_line:
        raise FunctionCallValidationError(
            f'Invalid symbol_id {symbol_id!r}; use an id returned by find_symbols or read(type="symbols").'
        )
    return raw_path, raw_name, start_line, end_line


def _coerce_optional_int(value: object, field_name: str) -> int | None:
    if value is None or value == '':
        return None
    try:
        return int(cast(Any, value))
    except (TypeError, ValueError) as exc:
        raise FunctionCallValidationError(f'{field_name} must be an integer.') from exc


def _filter_symbol_candidates(
    candidates: list[dict[str, Any]],
    *,
    symbol_name: str,
    parent_symbol: str | None = None,
    occurrence: int | None = None,
) -> list[dict[str, Any]]:
    filtered = [
        c
        for c in candidates
        if c.get('name') == symbol_name or c.get('qualified_name') == symbol_name
    ]
    if parent_symbol:
        filtered = [
            c
            for c in filtered
            if c.get('parent') == parent_symbol
            or str(c.get('qualified_name') or '').startswith(f'{parent_symbol}.')
        ]
    if occurrence is not None:
        if occurrence < 1 or occurrence > len(filtered):
            raise FunctionCallValidationError(
                f'Occurrence {occurrence} is out of range for {symbol_name}; '
                f'{len(filtered)} candidate(s) found.'
            )
        filtered = [filtered[occurrence - 1]]
    return filtered


def _resolve_symbol_candidates(
    *,
    path: str,
    symbol_name: str,
    symbol_kind: str | None = None,
    parent_symbol: str | None = None,
    occurrence: int | None = None,
) -> tuple[Path, str, list[dict[str, Any]]]:
    safe_path = _safe_workspace_path(path, must_exist=True)
    content = _read_text_for_tool(safe_path)
    lookup_name = symbol_name
    if not parent_symbol and '.' in lookup_name:
        maybe_parent, _, maybe_name = lookup_name.rpartition('.')
        parent_symbol = maybe_parent or None
        lookup_name = maybe_name

    candidates = _find_symbol_candidates_in_file(
        safe_path,
        lookup_name.split('.')[-1],
        symbol_kind=symbol_kind,
        include_private=True,
    )
    candidates = _filter_symbol_candidates(
        candidates,
        symbol_name=lookup_name.split('.')[-1],
        parent_symbol=parent_symbol,
    )

    if occurrence is not None:
        if occurrence < 1 or occurrence > len(candidates):
            raise FunctionCallValidationError(
                f'Occurrence {occurrence} is out of range for {symbol_name}; '
                f'{len(candidates)} candidate(s) found.'
            )
        candidates = [candidates[occurrence - 1]]

    return safe_path, content, candidates


def _symbol_action_ambiguity_error(
    symbol_name: str, candidates: list[dict[str, Any]]
) -> str:
    from backend.execution.aes.structured_edit_errors import (
        compact_symbol_candidates,
        symbol_ambiguity_summary,
    )

    compact = compact_symbol_candidates(candidates)
    return (
        f'{symbol_ambiguity_summary(symbol_name, candidates)}\n'
        + json.dumps({'candidates': compact}, separators=(',', ':'))
    )


def _single_symbol_candidate(
    *,
    path: str,
    symbol_name: str,
    symbol_kind: str | None = None,
    parent_symbol: str | None = None,
    occurrence: int | None = None,
) -> tuple[Path, str, dict[str, Any]]:
    safe_path, content, candidates = _resolve_symbol_candidates(
        path=path,
        symbol_name=symbol_name,
        symbol_kind=symbol_kind,
        parent_symbol=parent_symbol,
        occurrence=occurrence,
    )
    if not candidates:
        raise FunctionCallValidationError(
            f"edit_symbol failed: symbol not found.\nFile: {path}\nSymbol: {symbol_name}"
        )
    if len(candidates) > 1:
        raise FunctionCallValidationError(
            _symbol_action_ambiguity_error(symbol_name, candidates)
        )
    return safe_path, content, candidates[0]
