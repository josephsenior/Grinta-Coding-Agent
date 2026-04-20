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
* `edit_mode`: safer non-code editing primitives — prefer these over giant free-form replaces for documents:
  - `format`: parser-based mutation for json/yaml/toml/markdown/html/xml.
  - `section`: anchor-bounded section edit.
  - `range`: line-range replacement with optional `expected_hash` (slice) or `expected_file_hash` (whole file as read).
  - `patch`: unified diff hunk apply with strict context — for strict apply or review, not the default editing style.

Default mental model: **`edit_mode`** / **`ast_code_editor`** for structured code edits; **minimal valid `file_text` on create**, then **`insert_text`** or line/range tools. Multi-file work: sequential **`ast_code_editor`** calls or checkpoints — there is no atomic batch string API.

Paths are project-relative or absolute under the project root. Do not use a ``/workspace`` path prefix — there is no virtual mount alias.

## STRING ARGUMENT ESCAPING RULES (critical)

`file_text`, `new_str`, `section_content`, and `patch_text` are **JSON strings**. Follow JSON escape rules — NOT Python/C repr rules:
- Newline in the content → the single escape sequence `\\n` on the wire (one backslash + n). This decodes to an actual newline character when written to disk.
- Double quote inside the content → `\\"` on the wire (one backslash + quote).
- Tab → `\\t`. Carriage return → `\\r`. Literal backslash → `\\\\`.
- **Never double-escape.** Writing `\\\\n` on the wire produces the two-character sequence `\\n` in the file, which is almost always wrong for HTML/CSS/JS/TS/Python.
- Unescaped raw newlines inside a JSON string literal are invalid JSON and will be rejected.

If the tool reports `Syntax validation failed` with a hint about literal escape residue, retry using the rules above.
"""
_SHORT_STR_REPLACE_EDITOR_DESCRIPTION = (
    'File viewing, creation, and editing tool. Commands: view_file, create_file, '
    'insert_text, undo_last_edit. Supports edit_mode=format|section|range|patch. '
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
                'The commands to run: `view_file`, `create_file`, `insert_text`, `undo_last_edit`.',
                [
                    'view_file',
                    'create_file',
                    'insert_text',
                    'undo_last_edit',
                ],
            ),
            'path': get_path_param(
                'Path to file or directory, relative to the project root (e.g. `README.md`, '
                '`src/main.py`) or an absolute path under that root.'
            ),
            'file_text': {
                'description': (
                    'Required for `create_file`. Full body of the file to create, as a JSON string. '
                    'Escape newlines as \\n (single backslash) and embedded double quotes as \\". '
                    'Do NOT double-escape (\\\\n produces the literal characters "\\n" in the file).'
                ),
                'type': 'string',
            },
            'new_str': {
                'description': (
                    'Text to insert for `insert_text` (required there). JSON string — '
                    'escape newlines as \\n, embedded quotes as \\".'
                ),
                'type': 'string',
            },
            'insert_line': {
                'description': 'Required for `insert_text`. Line number after which to insert `new_str`.',
                'type': 'integer',
            },
            'view_range': {
                'description': 'Optional for `view_file`. Line range [start, end] (1-indexed). Use [start, -1] for rest of file.',
                'items': {'type': 'integer'},
                'type': 'array',
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
                'description': (
                    'Replacement/insert content for edit_mode=section. JSON string — '
                    'escape newlines as \\n, embedded quotes as \\".'
                ),
                'type': 'string',
            },
            'patch_text': {
                'description': (
                    'Unified diff patch body for edit_mode=patch. JSON string — escape '
                    'newlines as \\n so the diff structure survives JSON decoding.'
                ),
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
