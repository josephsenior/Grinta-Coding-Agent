"""Ultimate Code Explorer - Read-Only Mode.

Uses Ultimate Editor for structure-aware code exploration.
Tree-sitter parsing for symbol finding, navigation, and analysis.
"""

from backend.llm.tool_types import make_function_chunk, make_tool_param

_ULTIMATE_EXPLORER_DESCRIPTION = """Structure-aware code explorer powered by Tree-sitter (40+ languages)

Provides symbol-based code exploration without modification.

COMMANDS:

1. `find_symbol` - Find a symbol's location
   Required: file_path, symbol_name
   Optional: symbol_type ("function", "class", "method")
   Supports dot notation: "MyClass.method_name"

2. `explore_file` - Get file structure overview
   Required: file_path
   Returns: All functions, classes, and their locations

3. `get_symbol_context` - Get detailed symbol information
   Required: file_path, symbol_name
   Returns: Docstring, parameters, type annotations, decorators

FEATURES:
- Language-agnostic: Python, JS, TS, Go, Rust, Java, C++, etc.
- Fast symbol lookup (no line-by-line search)
- Structure awareness (understands code hierarchy)
- No modifications (100% safe exploration)

BEST PRACTICES:
1. Use `find_symbol` to locate functions/classes quickly
2. Use `explore_file` to get file overview before diving in
3. Use `get_symbol_context` for detailed documentation

Example:
```
find_symbol(file_path="/workspace/app.py", symbol_name="process_data")
→ Found 'process_data' at lines 42-58 (function)

get_symbol_context(file_path="/workspace/app.py", symbol_name="process_data")
→ Docstring: "Process incoming data..."
  Parameters: ['data', 'options']
  Returns: 'ProcessedData'
```
"""


def create_ultimate_explorer_tool():
    """Create Ultimate Explorer tool for Auditor.

    Returns:
        ChatCompletionToolParam with structure-aware exploration

    """
    return make_tool_param(
        type="function",
        function=make_function_chunk(
            name="ultimate_explorer",
            description=_ULTIMATE_EXPLORER_DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "description": "The command to execute",
                        "enum": ["find_symbol", "explore_file", "get_symbol_context"],
                        "type": "string",
                    },
                    "file_path": {
                        "description": "Absolute path to the file",
                        "type": "string",
                    },
                    "symbol_name": {
                        "description": "Symbol name to find (supports 'Class.method' notation)",
                        "type": "string",
                    },
                    "symbol_type": {
                        "description": "Optional symbol type filter",
                        "enum": ["function", "class", "method"],
                        "type": "string",
                    },
                },
                "required": ["command", "file_path"],
            },
        ),
    )
