"""Structure Editor tool providing structure-aware editing for the Orchestrator agent."""

from backend.engine.contracts import ChatCompletionToolParam
from backend.engine.tools.common import (
    create_tool_definition,
    get_command_param,
    get_path_param,
    get_security_risk_param,
)

_DETAILED_STRUCTURE_EDITOR_DESCRIPTION = """Structure-aware editor powered by Tree-sitter (40+ languages)

This is a next-generation editor that understands code structure, not just text.

KEY ADVANTAGES over string matching:
- Edit by symbol name (function/class), not line numbers
- Never breaks on whitespace/indentation issues
- Works for Python, JS, TS, Go, Rust, Java, C++, and 35+ more languages
- Automatic syntax validation before saving
- Intelligent error messages with suggestions

COMMANDS:

1. `edit_symbol_body` - Edit a function by name (any language)
    Required: path, function_name, new_body
   Example: Edit function "process_data" in Python/JS/Go/Rust/etc.

2. `rename_symbol` - Rename a symbol throughout a file
    Required: path, old_name, new_name
   Example: Rename variable "oldName" to "newName" everywhere

3. `find_symbol` - Find a symbol's location
    Required: path, symbol_name
   Optional: symbol_type ("function", "class", "method")
   Supports dot notation: "MyClass.method_name"

4. `replace_range` - Replace lines with new code
    Required: path, start_line, end_line, new_code
   Auto-indents new code to match context

5. `normalize_indent` - Fix indentation in a file
    Required: path
   Optional: style ("spaces" or "tabs"), size (2, 4, 8)
   Automatically detects and normalizes to project standards

6. `create_file` - Create a new file with content
    Required: path, file_text
   Creates parent directories if needed

7. `view_file` - View a file's contents
    Required: path
   Returns the file's full content

8. `insert_text` - Insert code after a specific line
    Required: path, new_str, insert_line
    insert_line=0 inserts at the beginning of the file

9. `undo_last_edit` - Undo the last runtime file-editor change to this path (session-local, bounded). Applies to commands delegated to the string editor (`create_file`, `replace_text`, `insert_text`, etc.). Symbol-level commands (`edit_symbol_body`, `rename_symbol`, …) update the file directly and do not add to this undo stack—use checkpoints for those.

NOTE:
- Prefer this tool for structure-aware code edits.
- For non-code files or document-oriented edits (format/section/range/patch), prefer `str_replace_editor` with `edit_mode`.

FEATURES:
- Language-agnostic: Works with ALL languages via Tree-sitter
- Auto-indentation: New code automatically matches file style
- Syntax validation: Validates before saving (with rollback on error)
- Smart errors: Fuzzy matching suggests corrections for typos
- Whitespace intelligence: Never fails on tabs vs. spaces

BEST PRACTICES:
1. Use `edit_symbol_body` instead of line-based replacements when possible
2. Use `find_symbol` first to verify symbol exists
3. Trust the auto-indentation - it matches your file's style
4. For typos, check error messages - they suggest corrections
"""

_SHORT_STRUCTURE_EDITOR_DESCRIPTION = """Structure-aware editor for 40+ languages (Python, JS, TS, Go, Rust, Java, C++, etc.)

Commands: edit_symbol_body, rename_symbol, find_symbol, replace_range, normalize_indent,
          create_file, view_file, replace_text, insert_text, undo_last_edit
- Edits by symbol name (function/class), not line numbers
- Auto-indents code to match file style
- Validates syntax before saving
- Suggests fixes for typos/errors
- Prefer str_replace_editor edit_mode for non-code document edits
"""


def create_structure_editor_tool(
    use_short_description: bool = False,
) -> ChatCompletionToolParam:
    """Create the Structure Editor tool for the Orchestrator agent.

    Args:
        use_short_description: Whether to use short or detailed description

    Returns:
        ChatCompletionToolParam with the Structure Editor configuration

    """
    description = (
        _SHORT_STRUCTURE_EDITOR_DESCRIPTION
        if use_short_description
        else _DETAILED_STRUCTURE_EDITOR_DESCRIPTION
    )

    return create_tool_definition(
        name='ast_code_editor',
        description=description,
        properties={
            'command': get_command_param(
                'The command to execute',
                [
                    'edit_symbol_body',
                    'rename_symbol',
                    'find_symbol',
                    'replace_range',
                    'normalize_indent',
                    'create_file',
                    'view_file',
                    'replace_text',
                    'insert_text',
                    'undo_last_edit',
                ],
            ),
            'path': get_path_param('Path to the file to edit'),
            'function_name': {
                'type': 'string',
                'description': 'Name of the function to edit (required for edit_symbol_body)',
            },
            'new_body': {
                'type': 'string',
                'description': 'New content for the function (required for edit_symbol_body)',
            },
            'old_name': {
                'type': 'string',
                'description': 'Original name of the symbol (required for rename_symbol)',
            },
            'new_name': {
                'type': 'string',
                'description': 'New name for the symbol (required for rename_symbol)',
            },
            'symbol_name': {
                'type': 'string',
                'description': 'Name of the symbol to find (required for find_symbol)',
            },
            'symbol_type': {
                'type': 'string',
                'description': 'Type of symbol (function, class, method) for find_symbol',
                'enum': ['function', 'class', 'method'],
            },
            'start_line': {
                'type': 'integer',
                'description': 'Start line number (1-indexed) for replace_range',
            },
            'end_line': {
                'type': 'integer',
                'description': 'End line number (1-indexed) for replace_range',
            },
            'new_code': {
                'type': 'string',
                'description': 'New code to insert (required for replace_range)',
            },
            'style': {
                'type': 'string',
                'description': 'Indentation style (spaces, tabs) for normalize_indent',
                'enum': ['spaces', 'tabs'],
            },
            'size': {
                'type': 'integer',
                'description': 'Indentation size (2, 4, 8) for normalize_indent',
            },
            'file_text': {
                'description': 'Content to write to the file (for create_file command)',
                'type': 'string',
            },
            'new_str': {
                'description': 'Text to insert (for insert_text command)',
                'type': 'string',
            },
            'insert_line': {
                'description': 'Line number to insert after (0 for beginning of file, for insert_text command)',
                'type': 'integer',
            },
            'security_risk': get_security_risk_param(),
        },
        required=['command', 'path'],
    )
