"""Configuration for the string-replace editor tool used by Orchestrator."""

from backend.engine.contracts import ChatCompletionToolParam
from backend.engine.tools.common import (
    create_tool_definition,
    get_command_param,
    get_path_param,
    get_security_risk_param,
)
from backend.inference.tool_names import TEXT_EDITOR_TOOL_NAME

_DETAILED_TEXT_EDITOR_DESCRIPTION = """File viewing, creation, and editing tool.
* `read_file`: show file contents (cat -n) or list directory (2 levels). Supports binary formats: .xlsx, .pptx, .wav, .mp3, .pdf, .docx (not images).
* `create_file`: create a new file or fully overwrite an existing file with the given content. Requires `file_text` — full-file body. Prefer a **small, parser-valid stub** first, then extend with further edits; avoid dumping very large bodies in one call. On large existing source files, full overwrite is blocked unless you explicitly set `overwrite_existing=true`.
* `insert_text`: insert `new_str` after `insert_line`.
* `undo_last_edit`: revert the last successful edit/write to this file in the current session (bounded history). Prefer checkpoint/rollback for large reversions.
* `edit_mode`: deterministic non-code editing primitives:
  - `range`: line-range replacement. Provide `start_line`, `end_line`, and `new_str` to replace a specific block.
* `multi_edit`: atomic batch for text-style edits. Use this for coordinated non-symbol changes across one or more files. Supported per-item commands: `create_file`, `insert_text`, and `edit` with `edit_mode=range`. The whole batch commits or rolls back together.

Default mental model: **`start_file_edit` for file edits**; use **minimal valid `file_text` on create**, then **`edit_mode=range`** or **`insert_text`** to extend. Avoid brittle string replacement.

Paths are project-relative or absolute under the project root. Do not use a ``/workspace`` path prefix — there is no virtual mount alias.

## STRING ARGUMENT ESCAPING RULES (critical)

`file_text` and `new_str` are **JSON strings**. Follow JSON escape rules — NOT Python/C repr rules:
- Newline in the content → the single escape sequence `\\n` on the wire (one backslash + n). This decodes to an actual newline character when written to disk.
- Double quote inside the content → `\\"` on the wire (one backslash + quote).
- Tab → `\\t`. Carriage return → `\\r`. Literal backslash → `\\\\`.
- **Never double-escape.** Writing `\\\\n` on the wire produces the two-character sequence `\\n` in the file, which is almost always wrong for HTML/CSS/JS/TS/Python.
- Unescaped raw newlines inside a JSON string literal are invalid JSON and will be rejected.

If the tool reports `Syntax validation failed` with a hint about literal escape residue, retry using the rules above.
"""
_SHORT_TEXT_EDITOR_DESCRIPTION = (
    'File reading, creation, and editing tool. '
    'Commands: read_file, create_file, insert_text, undo_last_edit, multi_edit. '
    'create_file creates new files OR overwrites existing files, but large existing source files require overwrite_existing=true. '
    'Use edit_mode=range for deterministic edits. '
    'Use project-relative paths.\n'
)


def create_text_editor_tool(
    use_short_description: bool = False,
) -> ChatCompletionToolParam:
    """Create a string replacement editor tool for the agent.

    Args:
        use_short_description: Whether to use short or detailed description.

    Returns:
        ChatCompletionToolParam: The configured string replacement editor tool.

    """
    description = (
        _SHORT_TEXT_EDITOR_DESCRIPTION
        if use_short_description
        else _DETAILED_TEXT_EDITOR_DESCRIPTION
    )
    return create_tool_definition(
        name=TEXT_EDITOR_TOOL_NAME,
        description=description,
        properties={
            'command': get_command_param(
                'The commands to run: `read_file`, `create_file`, `insert_text`, `undo_last_edit`, `edit`, `multi_edit`. '
                'Use `command=edit` with `edit_mode=range` to edit existing files.',
                [
                    'read_file',
                    'create_file',
                    'insert_text',
                    'undo_last_edit',
                    'edit',
                    'multi_edit',
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
            'overwrite_existing': {
                'description': (
                    'Optional safety override for `create_file`. Required when intentionally fully rewriting '
                    'a large existing source-code file; otherwise prefer `edit_mode=range`.'
                ),
                'type': 'boolean',
            },
            'new_str': {
                'description': (
                    'Replacement text for `edit_mode=range` or `insert_text`. '
                    'JSON string — escape newlines as \\n, embedded quotes as \\".'
                ),
                'type': 'string',
            },
            'insert_line': {
                'description': 'Required for `insert_text`. Line number after which to insert `new_str`.',
                'type': 'integer',
            },
            'view_range': {
                'description': 'Optional for `read_file`. Line range [start, end] (1-indexed). Use [start, -1] for rest of file.',
                'items': {'type': 'integer'},
                'type': 'array',
            },
            'security_risk': get_security_risk_param(),
            'edit_mode': {
                'description': 'Optional edit strategy for write commands: range.',
                'type': 'string',
                'enum': ['range'],
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
            'file_edits': {
                'type': 'array',
                'description': (
                    'For multi_edit only: atomic ordered text edits across one or more files. '
                    'Each item requires path and command. Supported item commands: '
                    '`create_file` with `file_text`, `insert_text` with `insert_line` + `new_str`, '
                    'and `edit` with `edit_mode=range`, `start_line`, `end_line`, and `new_str`.'
                ),
                'items': {
                    'type': 'object',
                    'properties': {
                        'path': {'type': 'string'},
                        'command': {
                            'type': 'string',
                            'enum': ['create_file', 'insert_text', 'edit'],
                        },
                        'file_text': {'type': 'string'},
                        'new_str': {'type': 'string'},
                        'insert_line': {'type': 'integer'},
                        'edit_mode': {'type': 'string', 'enum': ['range']},
                        'start_line': {'type': 'integer'},
                        'end_line': {'type': 'integer'},
                        'expected_file_hash': {'type': 'string'},
                        'overwrite_existing': {'type': 'boolean'},
                    },
                    'required': ['path', 'command'],
                },
            },
        },
        required=['command', 'security_risk'],
    )
