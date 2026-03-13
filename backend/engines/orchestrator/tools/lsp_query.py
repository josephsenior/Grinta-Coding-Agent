"""lsp_query tool — code navigation via the language server.

Supports the following commands:
- ``find_definition``  locate where a symbol is defined
- ``find_references``  find all usages of a symbol
- ``hover``            read the docstring/type signature at a position
- ``list_symbols``     enumerate top-level definitions in a file

When pylsp is not installed the tool still executes but returns an
``available=False`` flag so the LLM can fall back to grep-based search.
"""

from __future__ import annotations

from typing import Any

from backend.events.action.code_nav import LspQueryAction

LSP_QUERY_TOOL_NAME = "lsp_query"


def create_lsp_query_tool() -> dict[str, Any]:
    """Return the OpenAI function-calling tool definition for lsp_query."""
    return {
        "type": "function",
        "function": {
            "name": LSP_QUERY_TOOL_NAME,
            "description": (
                "Query the language server for code navigation. "
                "Use instead of grep when you need precise cross-file navigation.\n\n"
                "Commands:\n"
                "  find_definition – jump to where a symbol is defined\n"
                "  find_references – find every usage of a symbol in the project\n"
                "  hover           – show the docstring / type signature of a symbol\n"
                "  list_symbols    – list all functions and classes defined in a file\n\n"
                "Falls back gracefully if the language server is not installed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "enum": [
                            "find_definition",
                            "find_references",
                            "hover",
                            "list_symbols",
                        ],
                        "description": "The navigation command to execute.",
                    },
                    "file": {
                        "type": "string",
                        "description": "Absolute path to the file to query.",
                    },
                    "line": {
                        "type": "integer",
                        "description": (
                            "1-based line number of the symbol. "
                            "Required for find_definition, find_references, and hover."
                        ),
                    },
                    "column": {
                        "type": "integer",
                        "description": (
                            "1-based column number of the symbol. "
                            "Required for find_definition, find_references, and hover. "
                            "Defaults to 1 if omitted."
                        ),
                    },
                    "symbol": {
                        "type": "string",
                        "description": (
                            "Optional symbol name filter for list_symbols. "
                            "Case-insensitive substring match."
                        ),
                    },
                },
                "required": ["command", "file"],
            },
        },
    }


def build_lsp_query_action(arguments: dict) -> LspQueryAction:
    """Build an LspQueryAction from tool call arguments."""
    from backend.core.errors import FunctionCallValidationError

    command = arguments.get("command", "")
    file = arguments.get("file", "")

    if not command:
        raise FunctionCallValidationError(
            'Missing required argument "command" in tool call lsp_query'
        )
    if not file:
        raise FunctionCallValidationError(
            'Missing required argument "file" in tool call lsp_query'
        )

    return LspQueryAction(
        file=file,
        command=command,
        line=int(arguments.get("line", 1)),
        column=int(arguments.get("column", 1)),
        symbol=str(arguments.get("symbol", "")),
    )
