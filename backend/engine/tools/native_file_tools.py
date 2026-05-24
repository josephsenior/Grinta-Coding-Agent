"""Native public file tools for the agent.

The public file editing API is intentionally small. Do not expose new mutation
tools to the model unless they fit the Read/Create/Edit-Symbols/Replace/Multiedit
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
    CREATE_TOOL_NAME,
    EDIT_SYMBOLS_TOOL_NAME,
    MULTIEDIT_TOOL_NAME,
    READ_TOOL_NAME,
    REPLACE_STRING_TOOL_NAME,
)


def create_read_tool() -> ChatCompletionToolParam:
    return create_tool_definition(
        name=READ_TOOL_NAME,
        description=(
            'Read file, line range, symbol content, or symbol candidates. '
            'For symbols, path is optional; unique symbols may be auto-resolved, '
            'and ambiguous symbols return candidates.'
        ),
        properties={
            'type': {
                'type': 'string',
                'enum': ['file', 'range', 'symbol', 'symbols'],
                'description': 'Read kind: file, range, symbol body, or symbol candidates.',
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
                'description': 'Optional stable symbol id returned by read(type="symbols").',
            },
            'symbol_name': {
                'type': 'string',
                'description': 'Symbol name for type=symbol or type=symbols.',
            },
            'query': {
                'type': 'string',
                'description': 'Alias for symbol_name when type=symbols.',
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
            'by symbol_id, path+symbol, or a globally unique symbol name; ambiguous targets reject with candidates.'
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


def create_multiedit_tool() -> ChatCompletionToolParam:
    return create_tool_definition(
        name=MULTIEDIT_TOOL_NAME,
        description=(
            'Atomic multi-file refactoring. Operations use the same capabilities as '
            'create, edit_symbols, and replace_string. Not for casual single-file edits.'
        ),
        properties={
            'operations': {
                'type': 'array',
                'description': 'Atomic operations. Supported commands: create, edit_symbols, replace_string.',
                'items': {
                    'type': 'object',
                    'properties': {
                        'command': {'type': 'string'},
                        'type': {'type': 'string'},
                        'path': {'type': 'string'},
                        'content': {'type': 'string'},
                        'target_symbol': {'type': 'string'},
                        'target_kind': {'type': 'string'},
                        'position': {'type': 'string'},
                        'old_string': {'type': 'string'},
                        'new_string': {'type': 'string'},
                        'replace_all': {'type': 'boolean'},
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
    'create_multiedit_tool',
    'create_read_tool',
    'create_replace_string_tool',
]
