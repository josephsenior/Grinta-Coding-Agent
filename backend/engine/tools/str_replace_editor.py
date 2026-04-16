"""Configuration for the string-replace editor tool used by Orchestrator."""

from backend.engine.contracts import ChatCompletionToolParam
from backend.engine.tools.common import (
    create_tool_definition,
    get_command_param,
    get_path_param,
    get_security_risk_param,
)
from backend.inference.tool_names import STR_REPLACE_EDITOR_TOOL_NAME

_DETAILED_STR_REPLACE_EDITOR_DESCRIPTION = """File viewing, creation, and editing tool.
* `view_file`: show file contents (cat -n) or list directory (2 levels). Supports binary formats: .xlsx, .pptx, .wav, .mp3, .pdf, .docx (not images).
* `create_file`: create new file (fails if exists). Requires `file_text` — full-file body for new files. Prefer a **small, parser-valid stub** first, then extend with further edits; avoid dumping very large bodies in one call.
* `insert_text`: insert `new_str` after `insert_line`.
* `undo_last_edit`: revert the last successful edit/write to this file in the current session (bounded history). Prefer checkpoint/rollback for large reversions.
* `view_and_replace`: view + replace in one call. `view_range` scopes both display and match. Kept for compatibility.
* `batch_replace`: atomic multi-file edits. Provide `edits` array of {path, old_str, new_str}. All succeed or all roll back. Edits are validated in order (later `old_str` must not be trapped inside an earlier `new_str` on the same path).
* `edit_mode`: safer non-code editing primitives — prefer these over giant free-form replaces for documents:
  - `format`: parser-based mutation for json/yaml/toml/markdown/html/xml.
  - `section`: anchor-bounded section edit.
  - `range`: line-range replacement with optional `expected_hash` (slice) or `expected_file_hash` (whole file as read).
  - `patch`: unified diff hunk apply with strict context — for strict apply or review, not the default editing style.

Default mental model: **surgical replace** for code edits; **minimal valid `file_text` on create**, then iterate; **full `file_text`** only when truly replacing a whole file; **patch** when you need diff-shaped context.

Paths are project-relative or absolute under the project root. Do not use a ``/workspace`` path prefix — there is no virtual mount alias.
"""
_SHORT_STR_REPLACE_EDITOR_DESCRIPTION = (
    'File viewing, creation, and editing tool. Commands: view_file, create_file, '
    'insert_text, undo_last_edit, view_and_replace, batch_replace. Supports edit_mode=format|section|range|patch. '
    'Use project-relative paths.\n'
)


def create_str_replace_editor_tool(
    use_short_description: bool = False,
) -> ChatCompletionToolParam:
    """Create a string replacement editor tool for the agent.

    Args:
        use_short_description: Whether to use short or detailed description.

    Returns:
        ChatCompletionToolParam: The configured string replacement editor tool.

    """
    description = (
        _SHORT_STR_REPLACE_EDITOR_DESCRIPTION
        if use_short_description
        else _DETAILED_STR_REPLACE_EDITOR_DESCRIPTION
    )
    return create_tool_definition(
        name=STR_REPLACE_EDITOR_TOOL_NAME,
        description=description,
        properties={
            'command': get_command_param(
                'The commands to run: `view_file`, `create_file`, `insert_text`, `undo_last_edit`, `view_and_replace`, `batch_replace`.',
                [
                    'view_file',
                    'create_file',
                    'insert_text',
                    'undo_last_edit',
                    'view_and_replace',
                    'batch_replace',
                ],
            ),
            'path': get_path_param(
                'Path to file or directory, relative to the project root (e.g. `README.md`, '
                '`src/main.py`) or an absolute path under that root.'
            ),
            'file_text': {
                'description': 'Required for `create_file`. Content of the file to create.',
                'type': 'string',
            },
            'old_str': {
                'description': 'Exact string to replace (used by compatibility flows like `view_and_replace` and `batch_replace`).',
                'type': 'string',
            },
            'new_str': {
                'description': 'Replacement string (compatibility flows) or text to insert for `insert_text`.',
                'type': 'string',
            },
            'insert_line': {
                'description': 'Required for `insert_text`. Line number after which to insert `new_str`.',
                'type': 'integer',
            },
            'view_range': {
                'description': 'Optional for `view_file`/`view_and_replace`. Line range [start, end] (1-indexed). Use [start, -1] for rest of file.',
                'items': {'type': 'integer'},
                'type': 'array',
            },
            'edits': {
                'description': 'Required for `batch_replace`. Array of {path, old_str, new_str} edits applied atomically.',
                'type': 'array',
                'items': {
                    'type': 'object',
                    'properties': {
                        'path': {
                            'type': 'string',
                            'description': 'Absolute file path.',
                        },
                        'old_str': {
                            'type': 'string',
                            'description': 'Exact text to replace.',
                        },
                        'new_str': {
                            'type': 'string',
                            'description': 'Replacement text.',
                        },
                    },
                    'required': ['path', 'old_str', 'new_str'],
                },
            },
            'security_risk': get_security_risk_param(),
            'preview': {
                'description': 'If true, dry-run the edit without modifying the file.',
                'type': 'boolean',
            },
            'confidence': {
                'description': '0.0–1.0 certainty. Below 0.7 auto-runs in preview mode.',
                'type': 'number',
                'minimum': 0.0,
                'maximum': 1.0,
            },
            'edit_mode': {
                'description': 'Optional edit strategy for write commands: format, section, range, patch.',
                'type': 'string',
                'enum': ['format', 'section', 'range', 'patch'],
            },
            'format_kind': {
                'description': 'Required when edit_mode=format. Parser target kind.',
                'type': 'string',
                'enum': ['json', 'yaml', 'toml', 'markdown', 'html', 'xml'],
            },
            'format_op': {
                'description': 'Operation for edit_mode=format: set/delete/append.',
                'type': 'string',
                'enum': ['set', 'delete', 'append'],
            },
            'format_path': {
                'description': 'Path/key for format edits (e.g. $.scripts.build).',
                'type': 'string',
            },
            'format_value': {
                'description': 'Value for format set/append operations. JSON-compatible value or string.',
            },
            'anchor_type': {
                'description': 'Anchor selector type when edit_mode=section.',
                'type': 'string',
                'enum': ['markdown_heading', 'literal', 'regex'],
            },
            'anchor_value': {
                'description': 'Anchor text/pattern when edit_mode=section.',
                'type': 'string',
            },
            'anchor_occurrence': {
                'description': '1-indexed match occurrence for section anchor.',
                'type': 'integer',
            },
            'section_action': {
                'description': 'Section edit action for edit_mode=section.',
                'type': 'string',
                'enum': ['replace', 'insert_before', 'insert_after', 'delete'],
            },
            'section_content': {
                'description': 'Replacement/insert content for edit_mode=section.',
                'type': 'string',
            },
            'patch_text': {
                'description': 'Unified diff patch body for edit_mode=patch.',
                'type': 'string',
            },
            'expected_hash': {
                'description': 'Optional SHA-256 hash guard for range edits (computed over target slice text).',
                'type': 'string',
            },
            'expected_file_hash': {
                'description': (
                    'Optional SHA-256 (hex) of full file UTF-8 bytes as last read. '
                    'Rejects the edit if disk content does not match (staleness / wrong context).'
                ),
                'type': 'string',
            },
            'start_line': {
                'description': '1-based start line when using edit_mode=range.',
                'type': 'integer',
            },
            'end_line': {
                'description': '1-based end line (inclusive) when using edit_mode=range.',
                'type': 'integer',
            },
        },
        required=['command', 'path'],
    )
