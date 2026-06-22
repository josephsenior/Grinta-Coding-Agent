"""Native public file tools for the agent.

The public file API separates creation from editing: ``create`` creates new
files/symbols, while editing existing content is limited to ``replace_string``,
``edit_symbol``, and ``multiedit``.
"""

from __future__ import annotations

from backend.core.tools.tool_names import (
    CREATE_TOOL_NAME,
    EDIT_SYMBOL_TOOL_NAME,
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
            'symbols auto-resolve; ambiguous symbols return candidates, not guessed bodies.'
        ),
        properties={
            'type': {
                'type': 'string',
                'enum': ['file', 'symbols'],
                'description': 'Read kind: file (optionally a line range) or symbol bodies.',
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
        required=['type'],
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
            'Create a new file or a new code symbol. type=file overwrites existing files by default. '
            'type=symbol inserts a complete new symbol relative to an existing symbol.'
        ),
        properties={
            'type': {
                'type': 'string',
                'enum': ['file', 'symbol'],
                'description': 'Creation kind.',
            },
            'path': get_path_param('Project-relative target path.'),
            'content': {
                'type': 'string',
                'description': 'Raw file content or complete symbol text. Use real newlines.',
            },
            'target_symbol': {
                'type': 'string',
                'description': 'Existing symbol anchor for type=symbol.',
            },
            'target_kind': {
                'type': 'string',
                'description': 'Optional target kind filter: function, class, or method.',
            },
            'parent_symbol': {
                'type': 'string',
                'description': 'Optional parent/container symbol for disambiguation.',
            },
            'occurrence': {
                'type': 'integer',
                'description': 'Optional 1-based occurrence index after candidate discovery.',
            },
            'position': {
                'type': 'string',
                'enum': ['before', 'after', 'inside_start', 'inside_end'],
                'description': 'Where type=symbol inserts relative to target_symbol.',
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


def create_edit_symbol_tool() -> ChatCompletionToolParam:
    return create_tool_definition(
        name=EDIT_SYMBOL_TOOL_NAME,
        description=(
            'AST-aware edit or delete for one existing symbol in one file. '
            'Anchor by path plus qualified_name/symbol_name when possible. '
            'Ambiguous targets reject with candidates. '
            'For multiple symbols, multiple ops on one file, or cross-file batches, use multiedit.'
        ),
        properties={
            'path': get_path_param('Project-relative source file path.'),
            'symbol_id': {
                'type': 'string',
                'description': 'Optional stable symbol identifier from find_symbols or read.',
            },
            'qualified_name': {
                'type': 'string',
                'description': 'Preferred disambiguated symbol name (e.g. ClassName.method).',
            },
            'symbol_name': {
                'type': 'string',
                'description': 'Simple symbol name when qualified_name is unavailable.',
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
                'description': 'Optional 1-based occurrence index after candidate discovery.',
            },
            'new_content': {
                'type': 'string',
                'description': 'Complete replacement symbol text; empty string deletes when syntax remains valid.',
            },
            'security_risk': get_security_risk_param(),
        },
        required=['path', 'new_content', 'security_risk'],
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
            'Atomic batch refactoring: multiple operations and/or multiple files in one call. '
            'Use when several edits must land together (implementation + tests, multiple symbols, '
            'ordered string replacements, or mixing replace_string with edit_symbol). '
            'Each operation is either replace_string or edit_symbol. '
            'Not for a single one-off edit — use replace_string or edit_symbol instead.'
        ),
        properties={
            'operations': {
                'type': 'array',
                'description': 'Atomic operations. Supported commands: edit_symbol, replace_string.',
                'items': {
                    'type': 'object',
                    'properties': {
                        'command': {'type': 'string'},
                        'path': {'type': 'string'},
                        'old_string': {'type': 'string'},
                        'new_string': {'type': 'string'},
                        'replace_all': {'type': 'boolean'},
                        'qualified_name': {'type': 'string'},
                        'symbol_name': {'type': 'string'},
                        'symbol_kind': {'type': 'string'},
                        'parent_symbol': {'type': 'string'},
                        'occurrence': {'type': 'integer'},
                        'new_content': {'type': 'string'},
                        'edits': {'type': 'array'},
                    },
                    'required': ['command'],
                },
            },
            'security_risk': get_security_risk_param(),
        },
        required=['operations', 'security_risk'],
    )


__all__ = [
    'create_create_tool',
    'create_edit_symbol_tool',
    'create_find_symbols_tool',
    'create_multiedit_tool',
    'create_read_tool',
    'create_replace_string_tool',
    'create_undo_last_edit_tool',
]
