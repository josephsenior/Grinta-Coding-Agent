"""Native public file tools for the agent.

The public file API separates creation from editing: ``create`` creates new
files/symbols, while editing existing content is limited to ``replace_string``,
``edit_symbols``, and ``multiedit``.
"""

from __future__ import annotations

from backend.engine.contracts import ChatCompletionToolParam
from backend.engine.tools.common import (
    create_tool_definition,
    get_path_param,
    get_security_risk_param,
)
from backend.inference.tool_names import (
    CREATE_TOOL_NAME,
    EDIT_SYMBOLS_TOOL_NAME,
    FIND_SYMBOLS_TOOL_NAME,
    MULTIEDIT_TOOL_NAME,
    READ_TOOL_NAME,
    REPLACE_STRING_TOOL_NAME,
    UNDO_LAST_EDIT_TOOL_NAME,
)


def create_read_tool() -> ChatCompletionToolParam:
    return create_tool_definition(
        name=READ_TOOL_NAME,
        description=(
            'Read a file, line range, or one or more symbol bodies. Symbol reads are '
            'read-only: path is optional, unique symbols may be auto-resolved, and '
            'ambiguous symbols return candidates instead of guessed content.'
        ),
        properties={
            'type': {
                'type': 'string',
                'enum': ['file', 'range', 'symbols'],
                'description': 'Read kind: complete file, line range, or one/more symbol bodies.',
            },
            'path': get_path_param('Optional project-relative path. Required for file/range reads.'),
            'start_line': {
                'type': 'integer',
                'description': '1-based inclusive start line for type=range.',
            },
            'end_line': {
                'type': 'integer',
                'description': '1-based inclusive end line for type=range. Use -1 for EOF.',
            },
            'symbol_id': {
                'type': 'string',
                'description': 'Optional internal precision target returned by symbol discovery.',
            },
            'qualified_name': {
                'type': 'string',
                'description': 'Human-readable symbol target such as AuthService.login.',
            },
            'symbol_name': {
                'type': 'string',
                'description': 'Single unqualified symbol name for type=symbols when symbols[] is omitted.',
            },
            'query': {
                'type': 'string',
                'description': 'Alias for symbol_name when type=symbols.',
            },
            'symbols': {
                'type': 'array',
                'description': (
                    'One or more symbol targets for type=symbols. Each item may be an object '
                    'with qualified_name or symbol_name plus optional path/kind/parent/occurrence.'
                ),
                'items': {
                    'type': 'object',
                    'properties': {
                        'symbol_id': {'type': 'string'},
                        'qualified_name': {'type': 'string'},
                        'symbol_name': {'type': 'string'},
                        'path': {'type': 'string'},
                        'symbol_kind': {'type': 'string'},
                        'parent_symbol': {'type': 'string'},
                        'occurrence': {'type': 'integer'},
                    },
                },
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
            'include_private': {
                'type': 'boolean',
                'description': 'Whether type=symbols includes private/underscore-prefixed symbols.',
            },
            'security_risk': get_security_risk_param(),
        },
        required=['type', 'security_risk'],
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
            'security_risk': get_security_risk_param(),
        },
        required=['query', 'security_risk'],
    )


def create_create_tool() -> ChatCompletionToolParam:
    return create_tool_definition(
        name=CREATE_TOOL_NAME,
        description=(
            'Create a new file or a new code symbol. type=file never overwrites. '
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
        required=['type', 'path', 'content', 'security_risk'],
    )


def create_replace_string_tool() -> ChatCompletionToolParam:
    return create_tool_definition(
        name=REPLACE_STRING_TOOL_NAME,
        description=(
            'Exact text replacement in one file. Use for generic text edits, '
            'additions by replacing an anchor with anchor plus new content, and '
            'deletions by replacing with an empty string.'
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


def create_edit_symbols_tool() -> ChatCompletionToolParam:
    return create_tool_definition(
        name=EDIT_SYMBOLS_TOOL_NAME,
        description=(
            'AST-aware edit/delete for one or more existing symbols. Writes must be anchored '
            'by path+qualified_name+symbol_kind when possible, or another uniquely resolving target. '
            'Ambiguous targets reject with candidates.'
        ),
        properties={
            'path': get_path_param('Optional project-relative source file path. Strongly preferred for writes.'),
            'edits': {
                'type': 'array',
                'description': 'Symbol replacements/deletions to apply atomically.',
                'items': {
                    'type': 'object',
                    'properties': {
                        'symbol_id': {'type': 'string'},
                        'path': {'type': 'string'},
                        'qualified_name': {'type': 'string'},
                        'symbol_name': {'type': 'string'},
                        'symbol_kind': {'type': 'string'},
                        'parent_symbol': {'type': 'string'},
                        'occurrence': {'type': 'integer'},
                        'new_content': {
                            'type': 'string',
                            'description': 'Complete replacement symbol text; empty string deletes when syntax remains valid.',
                        },
                    },
                    'required': ['new_content'],
                },
            },
            'security_risk': get_security_risk_param(),
        },
        required=['edits', 'security_risk'],
    )


def create_undo_last_edit_tool() -> ChatCompletionToolParam:
    return create_tool_definition(
        name=UNDO_LAST_EDIT_TOOL_NAME,
        description=(
            'Undo the last file-write operation on the given file path. '
            'Only works on existing files — if the file no longer exists, '
            'this tool will report an error; use delete or create instead.'
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
            'Atomic multi-file refactoring. Operations use replace_string and '
            'edit_symbols. Not for casual single-file edits.'
        ),
        properties={
            'operations': {
                'type': 'array',
                'description': 'Atomic operations. Supported commands: edit_symbols, replace_string.',
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
    'create_edit_symbols_tool',
    'create_find_symbols_tool',
    'create_multiedit_tool',
    'create_read_tool',
    'create_replace_string_tool',
    'create_undo_last_edit_tool',
]
