"""Configuration for the string-replace editor tool used by Orchestrator."""

from backend.engine.tools.common import (
    create_tool_definition,
    get_command_param,
    get_path_param,
    get_security_risk_param,
)
from backend.engine.contracts import ChatCompletionToolParam
from backend.inference.tool_names import STR_REPLACE_EDITOR_TOOL_NAME

_DETAILED_STR_REPLACE_EDITOR_DESCRIPTION = """File viewing, creation, and editing tool.
* `view_file`: show file contents (cat -n) or list directory (2 levels). Supports binary formats: .xlsx, .pptx, .wav, .mp3, .pdf, .docx (not images).
* `create_file`: create new file (fails if exists). Requires `file_text`.
* `replace_text`: replace exact match of `old_str` with `new_str`. Must be unique in file. Include 3-5 context lines.
* `insert_text`: insert `new_str` after `insert_line`.
* `undo_last_edit`: revert last edit at `path`.
* `view_and_replace`: view + replace in one call. `view_range` scopes both display and match.
* `batch_replace`: atomic multi-file edits. Provide `edits` array of {path, old_str, new_str}. All succeed or all roll back.

Use absolute paths. `normalize_ws: true` ignores whitespace differences when matching.
"""
_SHORT_STR_REPLACE_EDITOR_DESCRIPTION = "File viewing, creation, and editing tool. Commands: view_file, create_file, replace_text, insert_text, undo_last_edit, view_and_replace, batch_replace. Use absolute paths. old_str must match exactly and uniquely.\n"


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
            "command": get_command_param(
                "The commands to run: `view_file`, `create_file`, `replace_text`, `insert_text`, `undo_last_edit`, `view_and_replace`, `batch_replace`.",
                [
                    "view_file",
                    "create_file",
                    "replace_text",
                    "insert_text",
                    "undo_last_edit",
                    "view_and_replace",
                    "batch_replace",
                ],
            ),
            "path": get_path_param(
                "Absolute path to file or directory, e.g. `/workspace/file.py` or `/workspace`."
            ),
            "file_text": {
                "description": "Required for `create_file`. Content of the file to create.",
                "type": "string",
            },
            "old_str": {
                "description": "Required for `replace_text`. Exact string to find and replace (must be unique).",
                "type": "string",
            },
            "new_str": {
                "description": "Replacement string for `replace_text`, or text to insert for `insert_text`.",
                "type": "string",
            },
            "insert_line": {
                "description": "Required for `insert_text`. Line number after which to insert `new_str`.",
                "type": "integer",
            },
            "view_range": {
                "description": "Optional for `view_file`/`view_and_replace`. Line range [start, end] (1-indexed). Use [start, -1] for rest of file.",
                "items": {"type": "integer"},
                "type": "array",
            },
            "normalize_ws": {
                "description": "If true, ignore whitespace differences when matching `old_str`.",
                "type": "boolean",
            },
            "edits": {
                "description": "Required for `batch_replace`. Array of {path, old_str, new_str} edits applied atomically.",
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Absolute file path."},
                        "old_str": {"type": "string", "description": "Exact text to replace."},
                        "new_str": {"type": "string", "description": "Replacement text."},
                    },
                    "required": ["path", "old_str", "new_str"],
                },
            },
            "security_risk": get_security_risk_param(),
            "preview": {
                "description": "If true, dry-run the edit without modifying the file.",
                "type": "boolean",
            },
            "confidence": {
                "description": "0.0–1.0 certainty. Below 0.7 auto-runs in preview mode.",
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
            },
        },
        required=["command", "path"],
    )
