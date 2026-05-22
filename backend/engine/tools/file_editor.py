"""Unified file editor tool for the Orchestrator agent."""

from backend.engine.contracts import ChatCompletionToolParam
from backend.engine.tools.common import (
    create_tool_definition,
    get_command_param,
    get_path_param,
    get_security_risk_param,
)
_DETAILED_DESCRIPTION = """Unified file editor: reading, creation, editing, and structure-aware refactoring.

COMMANDS (11):

Simple I/O:
  read             - Read file with line numbers or list directory (2 levels).
  create           - Create new file or overwrite existing. Requires content (full file body).
  insert           - Insert text after a line number. Requires insert_line and content.
  undo             - Undo last edit to this file in current session.

Line-range edit:
  replace_range    - Replace lines [start_line, end_line] with content.

Symbol-aware edits (Tree-sitter, 40+ languages):
  edit_symbol      - Edit function/method/class body by name.
  edit_symbols     - Batch edit multiple symbols in same file (max 25, atomic rollback).
  rename_symbol    - Rename symbol throughout file.
  find_symbol      - Find symbol location, type, line range.

Utilities:
  normalize_indent - Fix indentation to project standards.

Batch:
  multi_edit       - Atomic multi-file refactoring (cross-file, max 50 ops).
                     Uses nested <file_edit> XML blocks (no JSON arrays).
                     Each block contains: <path>, <operation>, <content>.

All commands require security_risk (LOW/MEDIUM/HIGH) and path (except multi_edit).

Paths are project-relative or absolute under the project root.
"""

_SHORT_DESCRIPTION = (
    "Unified file editor with 11 commands: read, create, insert, undo, "
    "replace_range, edit_symbol, "
    "edit_symbols, rename_symbol, find_symbol, normalize_indent, multi_edit. "
    "Uses XML format for code payloads."
)


def create_file_editor_tool(
    use_short_description: bool = False,
) -> ChatCompletionToolParam:
    """Create the unified file editor tool for the agent."""
    description = (
        _SHORT_DESCRIPTION if use_short_description else _DETAILED_DESCRIPTION
    )
    return create_tool_definition(
        name='file_editor',
        description=description,
        properties={
            'command': get_command_param(
                "The command to execute.",
                [
                    'read',
                    'create',
                    'insert',
                    'undo',
                    'replace_range',
                    'edit_symbol',
                    'edit_symbols',
                    'rename_symbol',
                    'find_symbol',
                    'normalize_indent',
                    'multi_edit',
                ],
            ),
            'path': get_path_param("Path to file or directory."),
            'content': {
                'description': "New content for the operation.",
                'type': 'string',
            },
            'overwrite_existing': {
                'description': "Safety override for create on large existing files.",
                'type': 'boolean',
            },
            'insert_line': {
                'description': "Line number to insert after (0 = beginning).",
                'type': 'integer',
            },
            'start_line': {
                'description': "1-based start line for replace_range.",
                'type': 'integer',
            },
            'end_line': {
                'description': "1-based inclusive end line for replace_range.",
                'type': 'integer',
            },
            'view_range': {
                'description': "Optional line range [start, end] for read.",
                'items': {'type': 'integer'},
                'type': 'array',
            },
            'expected_file_hash': {
                'description': "SHA-256 hash guard.",
                'type': 'string',
            },
            'symbol_name': {
                'type': 'string',
                'description': "Symbol name (supports dot notation).",
            },
            'symbol_type': {
                'type': 'string',
                'description': "Type filter for find_symbol.",
                'enum': ['function', 'class', 'method'],
            },
            'old_name': {
                'type': 'string',
                'description': "Current symbol name for rename_symbol.",
            },
            'new_name': {
                'type': 'string',
                'description': "New symbol name for rename_symbol.",
            },
            'line_number': {
                'type': 'integer',
                'description': "Disambiguation line for edit_symbol.",
            },
            'style': {
                'type': 'string',
                'description': "Indentation style for normalize_indent.",
                'enum': ['spaces', 'tabs'],
            },
            'size': {
                'type': 'integer',
                'description': "Indentation size for normalize_indent.",
            },
            'edits': {
                'type': 'array',
                'description': "For edit_symbols: list of {symbol_name, content} items.",
                'items': {
                    'type': 'object',
                    'properties': {
                        'symbol_name': {'type': 'string'},
                        'content': {'type': 'string'},
                    },
                    'required': ['symbol_name', 'content'],
                },
            },
            'file_edits': {
                'type': 'array',
                'description': "For multi_edit: atomic cross-file operations.",
                'items': {
                    'type': 'object',
                    'properties': {
                        'path': {'type': 'string'},
                        'operation': {
                            'type': 'string',
                            'enum': ['create', 'replace_range', 'edit_symbol', 'replace_file'],
                        },
                        'content': {'type': 'string'},
                        'start_line': {'type': 'integer'},
                        'end_line': {'type': 'integer'},
                        'symbol_name': {'type': 'string'},
                        'overwrite_existing': {'type': 'boolean'},
                        'expected_file_hash': {'type': 'string'},
                    },
                    'required': ['path', 'operation', 'content'],
                },
            },
            'security_risk': get_security_risk_param(),
        },
        required=['command', 'security_risk'],
    )
