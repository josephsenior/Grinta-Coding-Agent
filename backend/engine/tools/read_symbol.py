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
Read one exact symbol body/content. Use symbol_id from find_symbols when
available, or provide path plus symbol_name. If the target is ambiguous, the
tool returns candidates instead of guessing.
""".strip()


def create_read_symbol_tool() -> ChatCompletionToolParam:
    """Create the read_symbol tool definition."""
    return create_tool_definition(
        name=READ_SYMBOL_TOOL_NAME,
        description=_DESCRIPTION,
        properties={
            'symbol_id': {
                'type': 'string',
                'description': 'Optional symbol id returned by find_symbols.',
            },
            'path': {
                'type': 'string',
                'description': 'Project-relative source file path.',
            },
            'symbol_name': {
                'type': 'string',
                'description': 'Symbol name. Use Class.method for methods when helpful.',
            },
            'symbol_kind': {
                'type': 'string',
                'description': 'Optional kind filter: function, class, or method.',
            },
            'parent_symbol': {
                'type': 'string',
                'description': 'Optional parent/container symbol for disambiguation.',
            },
            'occurrence': {
                'type': 'integer',
                'description': 'Optional 1-based occurrence index if candidates were returned.',
            },
        },
        required=[],
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
