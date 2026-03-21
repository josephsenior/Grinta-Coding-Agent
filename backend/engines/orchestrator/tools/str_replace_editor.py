"""Configuration for the string-replace editor tool used by Orchestrator."""

from backend.engines.orchestrator.tools.common import (
    create_tool_definition,
    get_command_param,
    get_path_param,
    get_security_risk_param,
)
from backend.engines.orchestrator.contracts import ChatCompletionToolParam
from backend.llm.tool_names import STR_REPLACE_EDITOR_TOOL_NAME

_DETAILED_STR_REPLACE_EDITOR_DESCRIPTION = """Custom editing tool for viewing, creating and editing files in plain-text format
* Editor state is ephemeral to the current agent session and should not be relied upon for cross-run persistence. For step-level caching or long-term persistence, rely on the orchestrator's cache.
* If `path` is a text file, `view_file` displays the result of applying `cat -n`. If `path` is a directory, `view_file` lists non-hidden files and directories up to 2 levels deep
* The following binary file extensions can be viewed in Markdown format: [".xlsx", ".pptx", ".wav", ".mp3", ".m4a", ".flac", ".pdf", ".docx"]. IT DOES NOT HANDLE IMAGES.
* The `create_file` command cannot be used if the specified `path` already exists as a file
* If a `command` generates a long output, it will be truncated and marked with `<response clipped>`
* The `undo_last_edit` command will revert the last edit made to the file at `path`
* This tool can be used for creating and editing files in plain-text format.


Before using this tool:
1. Use the view tool to understand the file's contents and context
2. Verify the directory path is correct (only applicable when creating new files):
   - Use the view tool to verify the parent directory exists and is the correct location

When making edits:
   - Ensure the edit results in idiomatic, correct code
   - Do not leave the code in a broken state
   - Always use absolute file paths (starting with /)

CRITICAL REQUIREMENTS FOR USING THIS TOOL:

1. EXACT MATCHING: The `old_str` parameter must match EXACTLY one or more consecutive lines from the file, including all whitespace and indentation. The tool will fail if `old_str` matches multiple locations or doesn't match exactly with the file content.

2. UNIQUENESS: The `old_str` must uniquely identify a single instance in the file:
   - Include sufficient context before and after the change point (3-5 lines recommended)
   - If not unique, the replacement will not be performed

3. REPLACEMENT: The `new_str` parameter should contain the edited lines that replace the `old_str`. Both strings must be different.

Remember: when making multiple file edits in a row to the same file, you should prefer to send all edits in a single message with multiple calls to this tool, rather than multiple messages with a single call each.

COMPOUND COMMAND: `view_and_replace` — combines view_file + replace_text in ONE call.
   - Returns the file content (optionally scoped by `view_range`) AND applies the replacement.
   - When `view_range` is provided, `old_str` only needs to be unique within that range.
   - Eliminates stale reads: the returned content is always fresh.
   - Use this when you need to read a file section and edit it in a single step.

WHITESPACE TOLERANCE: Pass `normalize_ws: true` with `replace_text` or `view_and_replace`.
   - Ignores trailing whitespace and tab-vs-space differences when matching `old_str`.
   - The replacement uses the file's actual indentation, not your provided whitespace.
"""
_SHORT_STR_REPLACE_EDITOR_DESCRIPTION = "Custom editing tool for viewing, creating and editing files in plain-text format\n* Editor state is ephemeral to the current agent session and should not be relied upon for cross-run persistence. For step-level caching or long-term persistence, rely on the orchestrator's cache.\n* If `path` is a file, `view_file` displays the result of applying `cat -n`. If `path` is a directory, `view_file` lists non-hidden files and directories up to 2 levels deep\n* The `create_file` command cannot be used if the specified `path` already exists as a file\n* If a `command` generates a long output, it will be truncated and marked with `<response clipped>`\n* The `undo_last_edit` command will revert the last edit made to the file at `path`\nNotes for using the `replace_text` command:\n* The `old_str` parameter should match EXACTLY one or more consecutive lines from the original file. Be mindful of whitespaces!\n* If the `old_str` parameter is not unique in the file, the replacement will not be performed. Make sure to include enough context in `old_str` to make it unique\n* The `new_str` parameter should contain the edited lines that should replace the `old_str`\n"


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
                "The commands to run: `view_file`, `create_file`, `replace_text`, `insert_text`, `undo_last_edit`, `view_and_replace`.",
                [
                    "view_file",
                    "create_file",
                    "replace_text",
                    "insert_text",
                    "undo_last_edit",
                    "view_and_replace",
                ],
            ),
            "path": get_path_param(
                "Absolute path to file or directory, e.g. `/workspace/file.py` or `/workspace`."
            ),
            "file_text": {
                "description": "Required parameter of `create_file` command, with the content of the file to be created.",
                "type": "string",
            },
            "old_str": {
                "description": "Required parameter of `replace_text` command containing the string in `path` to replace.",
                "type": "string",
            },
            "new_str": {
                "description": "Optional parameter of `replace_text` command containing the new string (if not given, no string will be added). Required parameter of `insert_text` command containing the string to insert.",
                "type": "string",
            },
            "insert_line": {
                "description": "Required parameter of `insert_text` command. The `new_str` will be inserted AFTER the line `insert_line` of `path`.",
                "type": "integer",
            },
            "view_range": {
                "description": "Optional parameter of `view_file` and `view_and_replace` commands when `path` points to a file. If none is given, the full file is shown. If provided, the file will be shown in the indicated line number range, e.g. [11, 12] will show lines 11 and 12. Indexing at 1 to start. Setting `[start_line, -1]` shows all lines from `start_line` to the end of the file. For `view_and_replace`, limits the search scope for `old_str` to within this range.",
                "items": {"type": "integer"},
                "type": "array",
            },
            "normalize_ws": {
                "description": "Optional boolean for `replace_text` and `view_and_replace` commands. "
                    "If true, whitespace differences (trailing spaces, tabs vs spaces) are ignored when "
                    "matching `old_str`. The replacement preserves the file's original indentation style.",
                "type": "boolean",
            },
            "security_risk": get_security_risk_param(),
            "preview": {
                "description": "If true, show what the edit would produce without modifying the file. "
                    "Works with replace_text and insert_text commands. Returns a unified diff preview.",
                "type": "boolean",
            },
            "confidence": {
                "description": "Optional float 0.0–1.0 expressing how certain you are this edit is correct. "
                    "If below 0.7, the edit will automatically run in preview (dry-run) mode so the "
                    "result can be verified before the file is mutated. Use 1.0 when certain, 0.5 when "
                    "unsure about context/indentation, 0.3 when only partially certain.",
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
            },
        },
        required=["command", "path"],
    )
