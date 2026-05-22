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
                    'insert',
                    'replace_range',
                ],
            },
            'path': get_path_param('Project-relative path to the target file.'),
            'insert_line': {
                'type': 'integer',
                'description': 'Line number after which insert content is placed.',
            },
            'start_line': {
                'type': 'integer',
                'description': '1-based start line for replace_range.',
            },
            'end_line': {
                'type': 'integer',
                'description': '1-based inclusive end line for replace_range.',
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
            'security_risk': get_security_risk_param(),
        },
        required=['operation', 'security_risk'],
    )
