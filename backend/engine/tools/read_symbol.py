"""`read_symbol` tool.

Returns the source of a named symbol (function/class/method) or the full
contents of a file. Backed by the tree-sitter universal editor that ships
with Grinta as a core dependency, so it requires no optional extras.

Entity name format:
    "path/file.py:Symbol"             -- top-level symbol
    "path/file.py:Class.method"       -- method inside a class
    "path/file.py"                    -- whole file contents
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

from backend.engine.tools.common import create_tool_definition

if TYPE_CHECKING:
    from backend.engine.contracts import ChatCompletionToolParam

if TYPE_CHECKING:
    from backend.ledger.action import AgentThinkAction


READ_SYMBOL_TOOL_NAME = 'read_symbol'

_DESCRIPTION = """
Retrieve the full source of named symbols or files in one call.

Each entity is formatted as 'path/file.ext:Symbol' (top-level), 'path/file.ext:Class.method'
(method), or just 'path/file.ext' (whole file). Backed by tree-sitter so it works for
Python, JS/TS, Go, Rust, Java, C/C++, Ruby, PHP, and more.

Prefer this over `read_file` when you know the symbol name and want its definition without
loading the entire file. For text/regex search use `search_code`. For LSP-grade go-to-def,
hover, or references, use `lsp`.
""".strip()


def create_read_symbol_tool() -> ChatCompletionToolParam:
    """Create the read_symbol tool definition."""
    return create_tool_definition(
        name=READ_SYMBOL_TOOL_NAME,
        description=_DESCRIPTION,
        properties={
            'entity_names': {
                'type': 'array',
                'items': {'type': 'string'},
                'description': (
                    "List of entities to fetch. Format: 'path/file.py:Symbol', "
                    "'path/file.py:Class.method', or 'path/file.py' for whole file."
                ),
            },
        },
        required=['entity_names'],
    )


def _read_text(path: str, max_bytes: int = 200_000) -> str:
    """Read up to `max_bytes` of a file as UTF-8 text."""
    with open(path, 'rb') as fh:
        data = fh.read(max_bytes + 1)
    truncated = len(data) > max_bytes
    text = data[:max_bytes].decode('utf-8', errors='replace')
    if truncated:
        text += f'\n\n... [truncated at {max_bytes} bytes]'
    return text


def _extract_symbol(entity: str) -> dict[str, Any]:
    """Resolve a single 'path[:Symbol]' entity to its source body."""
    if ':' in entity:
        path, _, symbol = entity.partition(':')
    else:
        path, symbol = entity, ''

    path = path.strip()
    symbol = symbol.strip()

    if not path:
        return {'entity': entity, 'error': 'empty path'}
    if not os.path.exists(path):
        return {'entity': entity, 'error': f'file not found: {path}'}

    if not symbol:
        try:
            return {
                'entity': entity,
                'path': path,
                'kind': 'file',
                'content': _read_text(path),
            }
        except OSError as exc:
            return {'entity': entity, 'error': f'read failed: {exc}'}

    try:
        from backend.utils.treesitter_editor import (
            TREE_SITTER_AVAILABLE,
            TreeSitterEditor,
        )
    except ImportError as exc:
        return {'entity': entity, 'error': f'tree-sitter unavailable: {exc}'}

    if not TREE_SITTER_AVAILABLE:
        return {
            'entity': entity,
            'error': (
                'tree-sitter language pack not installed; '
                'use search_code + read_file or install tree-sitter-language-pack'
            ),
        }

    editor = TreeSitterEditor()
    location = editor.find_symbol(path, symbol)
    if location is None:
        return {
            'entity': entity,
            'error': f"symbol '{symbol}' not found in {path}",
        }

    try:
        with open(path, encoding='utf-8', errors='replace') as fh:
            lines = fh.readlines()
    except OSError as exc:
        return {'entity': entity, 'error': f'read failed: {exc}'}

    body = ''.join(lines[location.line_start - 1 : location.line_end])
    return {
        'entity': entity,
        'path': path,
        'kind': location.node_type,
        'symbol': location.symbol_name,
        'parent': location.parent_name,
        'line_start': location.line_start,
        'line_end': location.line_end,
        'content': body,
    }


def build_read_symbol_action(arguments: dict) -> AgentThinkAction:
    """Build action for read_symbol tool."""
    from backend.ledger.action import AgentThinkAction

    entity_names = arguments.get('entity_names') or []
    if isinstance(entity_names, str):
        entity_names = [entity_names]

    results = [_extract_symbol(str(e)) for e in entity_names]
    return AgentThinkAction(
        thought=f'[READ_SYMBOL]\n{json.dumps({"results": results}, indent=2)}'
    )
