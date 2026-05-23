"""Native public file/symbol tools for the agent."""

from __future__ import annotations

from backend.engine.contracts import ChatCompletionToolParam
from backend.engine.tools.common import (
    create_tool_definition,
    get_path_param,
    get_security_risk_param,
)
from backend.inference.tool_names import (
    CREATE_FILE_TOOL_NAME,
    FIND_SYMBOL_TOOL_NAME,
    READ_FILE_TOOL_NAME,
    RENAME_SYMBOL_TOOL_NAME,
    UNDO_LAST_EDIT_TOOL_NAME,
)


def create_read_file_tool() -> ChatCompletionToolParam:
    return create_tool_definition(
        name=READ_FILE_TOOL_NAME,
        description='Read a file. Optionally limit the response to a line range.',
        properties={
            'path': get_path_param('Project-relative path to read.'),
            'view_range': {
                'type': 'array',
                'items': {'type': 'integer'},
                'minItems': 2,
                'maxItems': 2,
                'description': 'Optional inclusive [start_line, end_line] view range.',
            },
            'security_risk': get_security_risk_param(),
        },
        required=['path', 'security_risk'],
    )


def create_create_file_tool() -> ChatCompletionToolParam:
    return create_tool_definition(
        name=CREATE_FILE_TOOL_NAME,
        description='Create a file or fully overwrite it with the provided content.',
        properties={
            'path': get_path_param('Project-relative path to write.'),
            'file_text': {
                'type': 'string',
                'description': 'Full file content.',
            },
            'overwrite_existing': {
                'type': 'boolean',
                'description': 'Required when intentionally overwriting an existing file.',
            },
            'security_risk': get_security_risk_param(),
        },
        required=['path', 'file_text', 'security_risk'],
    )


def create_undo_last_edit_tool() -> ChatCompletionToolParam:
    return create_tool_definition(
        name=UNDO_LAST_EDIT_TOOL_NAME,
        description='Undo the last runtime file-editor change for a path.',
        properties={
            'path': get_path_param('Project-relative path to restore.'),
            'security_risk': get_security_risk_param(),
        },
        required=['path', 'security_risk'],
    )


def create_rename_symbol_tool() -> ChatCompletionToolParam:
    return create_tool_definition(
        name=RENAME_SYMBOL_TOOL_NAME,
        description='Rename a symbol throughout a file.',
        properties={
            'path': get_path_param('Project-relative path to edit.'),
            'old_name': {
                'type': 'string',
                'description': 'Current symbol name.',
            },
            'new_name': {
                'type': 'string',
                'description': 'Replacement symbol name.',
            },
            'security_risk': get_security_risk_param(),
        },
        required=['path', 'old_name', 'new_name', 'security_risk'],
    )


def create_find_symbol_tool() -> ChatCompletionToolParam:
    return create_tool_definition(
        name=FIND_SYMBOL_TOOL_NAME,
        description='Locate a symbol in a file and return its line range.',
        properties={
            'path': get_path_param('Project-relative path to inspect.'),
            'symbol_name': {
                'type': 'string',
                'description': 'Name of the symbol to locate.',
            },
            'symbol_type': {
                'type': 'string',
                'description': 'Optional type filter such as function, class, or method.',
            },
            'security_risk': get_security_risk_param(),
        },
        required=['path', 'symbol_name', 'security_risk'],
    )


__all__ = [
    'create_create_file_tool',
    'create_find_symbol_tool',
    'create_read_file_tool',
    'create_rename_symbol_tool',
    'create_undo_last_edit_tool',
]
