"""Native public file tools for the agent.

The public file editing API is intentionally small. Do not expose new mutation
tools to the model unless they fit the Read/Create/Replace/Insert/AST-Multiedit
policy.
"""

from __future__ import annotations

from backend.engine.contracts import ChatCompletionToolParam
from backend.engine.tools.common import (
    create_tool_definition,
    get_path_param,
    get_security_risk_param,
)
from backend.inference.tool_names import (
    CREATE_FILE_TOOL_NAME,
    EDIT_SYMBOLS_TOOL_NAME,
    FIND_SYMBOLS_TOOL_NAME,
    INSERT_SYMBOL_TOOL_NAME,
    MULTIEDIT_TOOL_NAME,
    READ_FILE_TOOL_NAME,
    READ_RANGE_TOOL_NAME,
    REPLACE_STRING_TOOL_NAME,
    REPLACE_SYMBOL_TOOL_NAME,
)


def create_read_file_tool() -> ChatCompletionToolParam:
    return create_tool_definition(
        name=READ_FILE_TOOL_NAME,
        description=(
            'Read a complete small or medium-sized file. For large files or '
            'known locations, prefer read_range or read_symbol.'
        ),
        properties={
            'path': get_path_param('Project-relative path to read.'),
            'security_risk': get_security_risk_param(),
        },
        required=['path', 'security_risk'],
    )


def create_read_range_tool() -> ChatCompletionToolParam:
    return create_tool_definition(
        name=READ_RANGE_TOOL_NAME,
        description='Read a specific inclusive line range from a file. Read-only.',
        properties={
            'path': get_path_param('Project-relative path to read.'),
            'start_line': {
                'type': 'integer',
                'description': '1-based inclusive start line.',
            },
            'end_line': {
                'type': 'integer',
                'description': '1-based inclusive end line. Use -1 for EOF.',
            },
            'security_risk': get_security_risk_param(),
        },
        required=['path', 'start_line', 'end_line', 'security_risk'],
    )


def create_find_symbols_tool() -> ChatCompletionToolParam:
    return create_tool_definition(
        name=FIND_SYMBOLS_TOOL_NAME,
        description=(
            'Discover matching code symbols without modifying files. Use this '
            'when you know a symbol name but not the exact occurrence.'
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


def create_create_file_tool() -> ChatCompletionToolParam:
    return create_tool_definition(
        name=CREATE_FILE_TOOL_NAME,
        description=(
            'Create a new file with raw content. Never overwrites existing files; '
            'if the file exists, use replace_symbol or replace_string.'
        ),
        properties={
            'path': get_path_param('Project-relative path to create.'),
            'content': {
                'type': 'string',
                'description': 'Raw full file content. Use real newlines, not JSON-escaped \\n text.',
            },
            'security_risk': get_security_risk_param(),
        },
        required=['path', 'content', 'security_risk'],
    )


def create_replace_symbol_tool() -> ChatCompletionToolParam:
    return create_tool_definition(
        name=REPLACE_SYMBOL_TOOL_NAME,
        description=(
            'Replace or delete one existing code symbol. new_content must be '
            'the complete replacement symbol text, not a patch or changed lines.'
        ),
        properties={
            'path': get_path_param('Project-relative source file path.'),
            'symbol_name': {
                'type': 'string',
                'description': 'Name of the symbol to replace. Use Class.method for methods when helpful.',
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
                'description': 'Optional 1-based occurrence index if candidates were previously returned.',
            },
            'new_content': {
                'type': 'string',
                'description': 'Complete replacement symbol text. Empty string deletes the symbol when syntax remains valid.',
            },
            'security_risk': get_security_risk_param(),
        },
        required=['path', 'symbol_name', 'new_content', 'security_risk'],
    )


def create_insert_symbol_tool() -> ChatCompletionToolParam:
    return create_tool_definition(
        name=INSERT_SYMBOL_TOOL_NAME,
        description=(
            'Insert one complete new code symbol before, after, or inside an '
            'existing symbol. Use this for adding functions, methods, classes, '
            'handlers, or components.'
        ),
        properties={
            'path': get_path_param('Project-relative source file path.'),
            'target_symbol': {
                'type': 'string',
                'description': 'Existing symbol used as the structural insertion anchor.',
            },
            'target_kind': {
                'type': 'string',
                'description': 'Optional target kind filter: function, class, or method.',
            },
            'parent_symbol': {
                'type': 'string',
                'description': 'Optional parent/container symbol for disambiguation.',
            },
            'position': {
                'type': 'string',
                'enum': ['before', 'after', 'inside_start', 'inside_end'],
                'description': 'Where to insert relative to the target symbol.',
            },
            'content': {
                'type': 'string',
                'description': 'Complete raw symbol text to insert.',
            },
            'security_risk': get_security_risk_param(),
        },
        required=['path', 'target_symbol', 'position', 'content', 'security_risk'],
    )


def create_replace_string_tool() -> ChatCompletionToolParam:
    return create_tool_definition(
        name=REPLACE_STRING_TOOL_NAME,
        description=(
            'Exact text replacement for code and non-code. Use for generic '
            'text edits, additions by replacing an anchor with anchor plus new '
            'content, and deletions by replacing with an empty string.'
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
            'AST-aware batch edit for multiple symbols in one file. Use when '
            'editing several symbols together or when a single AST-aware batch '
            'is cleaner than many replace_symbol calls.'
        ),
        properties={
            'path': get_path_param('Project-relative source file path.'),
            'edits': {
                'type': 'array',
                'description': 'Symbol replacements to apply atomically within the file.',
                'items': {
                    'type': 'object',
                    'properties': {
                        'symbol_name': {'type': 'string'},
                        'new_content': {
                            'type': 'string',
                            'description': 'Replacement content for the symbol edit. Use real newlines, not escaped \\n text.',
                        },
                    },
                    'required': ['symbol_name', 'new_content'],
                },
            },
            'security_risk': get_security_risk_param(),
        },
        required=['path', 'edits', 'security_risk'],
    )


def create_multiedit_tool() -> ChatCompletionToolParam:
    return create_tool_definition(
        name=MULTIEDIT_TOOL_NAME,
        description=(
            'Atomic multi-file refactoring. Use for coordinated changes across '
            'files, such as implementation plus tests. Not for casual single-file edits.'
        ),
        properties={
            'operations': {
                'type': 'array',
                'description': (
                    'Atomic operations. Supported commands: create_file, replace_string, '
                    'and replace_symbol.'
                ),
                'items': {
                    'type': 'object',
                    'properties': {
                        'command': {'type': 'string'},
                        'path': {'type': 'string'},
                        'content': {'type': 'string'},
                        'old_string': {'type': 'string'},
                        'new_string': {'type': 'string'},
                        'replace_all': {'type': 'boolean'},
                        'symbol_name': {'type': 'string'},
                        'symbol_kind': {'type': 'string'},
                        'new_content': {'type': 'string'},
                    },
                    'required': ['command', 'path'],
                },
            },
            'security_risk': get_security_risk_param(),
        },
        required=['operations', 'security_risk'],
    )


__all__ = [
    'create_create_file_tool',
    'create_edit_symbols_tool',
    'create_find_symbols_tool',
    'create_insert_symbol_tool',
    'create_multiedit_tool',
    'create_read_file_tool',
    'create_read_range_tool',
    'create_replace_string_tool',
    'create_replace_symbol_tool',
]
