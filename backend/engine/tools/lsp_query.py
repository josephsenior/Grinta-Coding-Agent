"""code_intelligence tool — code navigation via the language server.

Supports the following commands:
- ``find_definition``  locate where a symbol is defined
- ``find_references``  find all usages of a symbol
- ``hover``            read the docstring/type signature at a position
- ``list_symbols``     enumerate top-level definitions in a file
- ``get_diagnostics``  get errors/warnings for a file (after editing)

When pylsp is not installed the tool still executes but returns an
``available=False`` flag so the LLM can fall back to grep-based search.
"""

from __future__ import annotations

from typing import Any

from backend.ledger.action.code_nav import LspQueryAction

CODE_INTELLIGENCE_TOOL_NAME = 'code_intelligence'


def create_lsp_query_tool() -> dict[str, Any]:
    """Return the OpenAI function-calling tool definition for code_intelligence."""
    return {
        'type': 'function',
        'function': {
            'name': CODE_INTELLIGENCE_TOOL_NAME,
            'description': (
                'Code navigation and diagnostics via language server. '
                'Commands: find_definition, find_references, hover, list_symbols, get_diagnostics. '
                'Use get_diagnostics after editing a file to check for errors/warnings. '
                'Use find_definition/find_references when you know the file and position. '
                'Falls back gracefully if LSP is not installed.'
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'command': {
                        'type': 'string',
                        'enum': [
                            'find_definition',
                            'find_references',
                            'hover',
                            'list_symbols',
                            'get_diagnostics',
                        ],
                        'description': (
                            'The command to execute. '
                            'get_diagnostics: get errors/warnings for a file (no line/column needed). '
                            'find_definition/find_references/hover: require line and column. '
                            'list_symbols: lists top-level definitions in a file.'
                        ),
                    },
                    'file': {
                        'type': 'string',
                        'description': 'Absolute path to the file to query.',
                    },
                    'line': {
                        'type': 'integer',
                        'description': (
                            '1-based line number of the symbol. '
                            'Required for find_definition, find_references, and hover.'
                        ),
                    },
                    'column': {
                        'type': 'integer',
                        'description': (
                            '1-based column number of the symbol. '
                            'Required for find_definition, find_references, and hover. '
                            'Defaults to 1 if omitted.'
                        ),
                    },
                    'symbol': {
                        'type': 'string',
                        'description': (
                            'Optional symbol name filter for list_symbols. '
                            'Case-insensitive substring match.'
                        ),
                    },
                },
                'required': ['command', 'file'],
            },
        },
    }


def build_lsp_query_action(arguments: dict) -> LspQueryAction:
    """Build an LspQueryAction from tool call arguments."""
    from backend.core.errors import FunctionCallValidationError

    command = arguments.get('command', '')
    file = arguments.get('file', '')

    if not command:
        raise FunctionCallValidationError(
            f'Missing required argument "command" in tool call {CODE_INTELLIGENCE_TOOL_NAME}'
        )
    if not file:
        raise FunctionCallValidationError(
            f'Missing required argument "file" in tool call {CODE_INTELLIGENCE_TOOL_NAME}'
        )

    return LspQueryAction(
        file=file,
        command=command,
        line=int(arguments.get('line', 1)),
        column=int(arguments.get('column', 1)),
        symbol=str(arguments.get('symbol', '')),
    )
