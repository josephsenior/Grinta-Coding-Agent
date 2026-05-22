"""Metadata-only entry point for two-mode file editing."""

from __future__ import annotations

from backend.engine.contracts import ChatCompletionToolParam
from backend.engine.tools.common import (
    create_tool_definition,
    get_path_param,
    get_security_risk_param,
)
from backend.inference.tool_names import START_FILE_EDIT_TOOL_NAME

_DESCRIPTION = """Initiates a file edit transaction. Use this for file edits.

Use metadata only. Never pass file content here; raw content is captured in FILE EDITOR MODE.
"""


def create_start_file_edit_tool() -> ChatCompletionToolParam:
    """Create the native metadata-only file edit starter tool."""
    return create_tool_definition(
        name=START_FILE_EDIT_TOOL_NAME,
        description=_DESCRIPTION,
        properties={
            'operation': {
                'type': 'string',
                'description': 'File operation to perform.',
                'enum': [
                    'read',
                    'create',
                    'insert',
                    'undo',
                    'replace_lines',
                    'format_edit',
                    'section_edit',
                    'patch',
                    'find_symbol',
                ],
            },
            'path': get_path_param('Project-relative path to the target file.'),
            'overwrite_existing': {
                'type': 'boolean',
                'description': 'Allow create to overwrite an existing file.',
            },
            'insert_line': {
                'type': 'integer',
                'description': 'Line number after which insert content is placed.',
            },
            'start_line': {
                'type': 'integer',
                'description': '1-based start line for replace_lines.',
            },
            'end_line': {
                'type': 'integer',
                'description': '1-based inclusive end line for replace_lines.',
            },
            'view_range': {
                'type': 'array',
                'description': 'Optional line range [start, end] for read.',
                'items': {'type': 'integer'},
            },
            'expected_file_hash': {
                'type': 'string',
                'description': 'Existing SHA-256 hash guard for the full file.',
            },
            'expected_old_hash': {
                'type': 'string',
                'description': 'Alias for the existing content hash guard.',
            },
            'expected_file_rev': {
                'type': 'string',
                'description': 'Optional caller-side file revision precondition.',
            },
            'expected_hash': {
                'type': 'string',
                'description': 'Operation-specific hash guard when supported.',
            },
            'format_kind': {
                'type': 'string',
                'description': 'Parser target for format_edit.',
                'enum': ['json', 'yaml', 'toml', 'markdown', 'html', 'xml'],
            },
            'format_op': {
                'type': 'string',
                'description': 'Parser operation for format_edit.',
            },
            'format_path': {
                'type': 'string',
                'description': 'Path/query inside the structured document.',
            },
            'format_value': {
                'description': 'JSON/YAML/TOML scalar or object for format_edit.',
            },
            'anchor_type': {
                'type': 'string',
                'description': 'Anchor kind for section_edit.',
                'enum': ['heading', 'regex', 'literal'],
            },
            'anchor_value': {
                'type': 'string',
                'description': 'Anchor value for section_edit.',
            },
            'anchor_occurrence': {
                'type': 'integer',
                'description': '1-based anchor occurrence for section_edit.',
            },
            'section_action': {
                'type': 'string',
                'description': 'Section operation.',
                'enum': ['replace', 'insert_after', 'insert_before', 'delete'],
            },
            'symbol_name': {
                'type': 'string',
                'description': 'Symbol name for edit_symbol or find_symbol.',
            },
            'symbol_kind': {
                'type': 'string',
                'description': 'Optional symbol kind.',
                'enum': ['function', 'class', 'method'],
            },
            'symbol_type': {
                'type': 'string',
                'description': 'Optional symbol type for find_symbol.',
            },
            'line_number': {
                'type': 'integer',
                'description': 'Optional disambiguation line for symbol edits.',
            },
            'security_risk': get_security_risk_param(),
        },
        required=['operation', 'security_risk'],
    )
