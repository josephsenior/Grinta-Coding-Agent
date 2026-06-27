"""Native public file tools for the agent.

The public file API separates creation from editing: ``create`` creates new
files, while editing existing content is limited to ``replace_string`` and
``multiedit`` (a batch of ``replace_string`` operations). Symbol discovery
lives in ``find_symbols`` and ``read(type=symbols)``.
"""

from __future__ import annotations

from backend.core.tools.tool_names import (
    CREATE_TOOL_NAME,
    FIND_SYMBOLS_TOOL_NAME,
    MULTIEDIT_TOOL_NAME,
    READ_TOOL_NAME,
    REPLACE_STRING_TOOL_NAME,
    UNDO_LAST_EDIT_TOOL_NAME,
)
from backend.engine.contracts import ChatCompletionToolParam
from backend.engine.tools.param_defs import (
    create_tool_definition,
    get_path_param,
    get_security_risk_param,
)


def create_read_tool() -> ChatCompletionToolParam:
    return create_tool_definition(
        name=READ_TOOL_NAME,
        description=(
            'Read a file, a line range within a file, or one or more symbol bodies. '
            'For files: use type=file with path; add start_line and end_line for a range. '
            'For symbols: use type=symbols with symbols[] (one or more targets). Unique '
            'symbols auto-resolve; ambiguous symbols return candidates, not guessed bodies. '
            'When type is omitted: path-only or line bounds infer file; symbols[] or '
            'qualified_name/symbol_name/symbol_id infer symbols.'
        ),
        properties={
            'type': {
                'type': 'string',
                'enum': ['file', 'symbols'],
                'description': (
                    'Read kind: file (optionally a line range) or symbol bodies. '
                    'Optional when path, symbols[], or symbol identifiers make the intent clear.'
                ),
            },
            'path': get_path_param(
                'Project-relative path. Required for type=file; optional default for all symbols[].'
            ),
            'start_line': {
                'type': 'integer',
                'description': '1-based inclusive start line for type=file line-range reads.',
            },
            'end_line': {
                'type': 'integer',
                'description': '1-based inclusive end line for type=file line-range reads. Use -1 for EOF.',
            },
            'symbols': {
                'type': 'array',
                'description': (
                    'Required for type=symbols. Each item needs qualified_name or symbol_name; '
                    'optional per-item path, symbol_kind, parent_symbol, occurrence, or symbol_id.'
                ),
                'items': {
                    'type': 'object',
                    'properties': {
                        'qualified_name': {'type': 'string'},
                        'symbol_name': {'type': 'string'},
                        'symbol_id': {'type': 'string'},
                        'path': {'type': 'string'},
                        'symbol_kind': {'type': 'string'},
                        'parent_symbol': {'type': 'string'},
                        'occurrence': {'type': 'integer'},
                    },
                },
            },
            'symbol_kind': {
                'type': 'string',
                'description': 'Default symbol kind for all symbols[] items (function, class, method).',
            },
        },
        required=[],
    )


def create_find_symbols_tool() -> ChatCompletionToolParam:
    return create_tool_definition(
        name=FIND_SYMBOLS_TOOL_NAME,
        description=(
            'Discover matching code symbols without reading full symbol bodies or modifying files. '
            'Use this when you know a symbol name but need candidate paths, qualified names, kinds, or line ranges.'
        ),
        properties={
            'query': {
                'type': 'string',
                'description': 'Symbol name or substring to find.',
            },
            'path': get_path_param(
                'Optional project-relative file path to search. If omitted, searches common source files.'
            ),
            'symbol_kind': {
                'type': 'string',
                'description': 'Optional kind filter: function, class, or method.',
            },
            'include_private': {
                'type': 'boolean',
                'description': 'Whether to include private/underscore-prefixed symbols.',
            },
        },
        required=['query'],
    )


def create_create_tool() -> ChatCompletionToolParam:
    return create_tool_definition(
        name=CREATE_TOOL_NAME,
        description=(
            'Create a new file. Fails if the file already exists; use replace_string '
            'or multiedit to modify an existing file.'
        ),
        properties={
            'path': get_path_param('Project-relative target path.'),
            'content': {
                'type': 'string',
                'description': 'Raw file content. Use real newlines.',
            },
            'security_risk': get_security_risk_param(),
        },
        required=['path', 'content', 'security_risk'],
    )


def create_replace_string_tool() -> ChatCompletionToolParam:
    return create_tool_definition(
        name=REPLACE_STRING_TOOL_NAME,
        description=(
            'Exact text replacement in one file. Use for generic text edits, '
            'additions by replacing an anchor with anchor plus new content, and '
            'deletions by replacing with an empty string. One replacement per call.'
        ),
        properties={
            'path': get_path_param('Project-relative path to edit.'),
            'old_string': {
                'type': 'string',
                'description': 'Exact text to replace. Must not be empty.',
            },
            'new_string': {
                'type': 'string',
                'description': 'Exact replacement text. May be empty for deletion.',
            },
            'replace_all': {
                'type': 'boolean',
                'description': 'Replace all exact occurrences. Default false requires exactly one match.',
            },
            'security_risk': get_security_risk_param(),
        },
        required=['path', 'old_string', 'new_string', 'security_risk'],
    )


def create_undo_last_edit_tool() -> ChatCompletionToolParam:
    return create_tool_definition(
        name=UNDO_LAST_EDIT_TOOL_NAME,
        description=(
            'Undo the last content edit on the given file path. '
            'Only restores a prior version when the file already existed before that edit. '
            'If the only recorded change was creating the file, this fails — delete the file '
            'explicitly instead. The file must still exist when you call this tool.'
        ),
        properties={
            'path': get_path_param('Project-relative path to undo the last edit on.'),
        },
        required=['path'],
    )


def create_multiedit_tool() -> ChatCompletionToolParam:
    return create_tool_definition(
        name=MULTIEDIT_TOOL_NAME,
        description=(
            'Atomic batch refactoring: multiple replace_string operations across one or more files. '
            'Use when several edits must land together (implementation + tests, multiple files, '
            'ordered string replacements). All operations succeed together or none are committed. '
            'Not for a single one-off edit — use replace_string instead.'
        ),
        properties={
            'operations': {
                'type': 'array',
                'description': 'Atomic replace_string operations.',
                'items': {
                    'type': 'object',
                    'properties': {
                        'path': get_path_param(
                            'Workspace-relative file path. Required for every operation.'
                        ),
                        'old_string': {'type': 'string'},
                        'new_string': {'type': 'string'},
                        'replace_all': {'type': 'boolean'},
                    },
                    'required': ['path', 'old_string', 'new_string'],
                },
            },
            'security_risk': get_security_risk_param(),
        },
        required=['operations', 'security_risk'],
    )


__all__ = [
    'create_create_tool',
    'create_find_symbols_tool',
    'create_multiedit_tool',
    'create_read_tool',
    'create_replace_string_tool',
    'create_undo_last_edit_tool',
]
