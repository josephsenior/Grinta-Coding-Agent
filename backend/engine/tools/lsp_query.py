"""lsp tool — code navigation via the language server.

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

from backend.core.tools.tool_names import CODE_INTELLIGENCE_TOOL_NAME, LSP_TOOL_NAME
from backend.ledger.action.code_nav import LspQueryAction


def create_lsp_query_tool() -> dict[str, Any]:
    """Return the OpenAI function-calling tool definition for lsp."""
    return {
        'type': 'function',
        'function': {
            'name': LSP_TOOL_NAME,
            'description': (
                'Read-only semantic code navigation via the locally-installed '
                'language server (LSP). Auto-detects servers on PATH (pylsp, '
                'pyright, typescript-language-server, gopls, rust-analyzer, '
                'clangd, …) — the System Capabilities block in the system prompt '
                'lists which are actually present on this host; do NOT shell out '
                'to discover them.\n'
                'Commands: find_definition, find_references, hover, list_symbols, '
                'get_diagnostics, code_action. Use get_diagnostics after editing a file to '
                'check for errors/warnings. Use find_definition / find_references '
                'when you know the file and 1-based position. Use code_action to '
                'discover quick-fixes / refactors the language server suggests for '
                'a file or position (auto-import, remove-unused, organize-imports, '
                'add-missing-match-arm, …); the result is a list of titles — apply '
                'the chosen fix yourself via a file edit and '
                're-run `get_diagnostics` to verify.\n'
                'Tool boundaries (do not duplicate effort):\n'
                '  • Edit by symbol name → use `edit_symbol`. `lsp` '
                'is read-only and intentionally does not expose rename.\n'
                '  • Workspace-wide text/symbol search → use `grep` or `glob` '
                '(ripgrep). `list_symbols` only enumerates symbols in a single file.\n'
                '  • Code formatting / quick-fix application → run the project '
                'formatter or linter via `execute_bash` / `execute_powershell`.\n'
                'When no LSP server is installed this tool is hidden from the '
                'toolset entirely — its absence here means the user has at least '
                'one server on PATH.'
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
                            'code_action',
                        ],
                        'description': (
                            'The command to execute. '
                            'get_diagnostics: get errors/warnings for a file (no line/column needed). '
                            'find_definition/find_references/hover: require line and column. '
                            'list_symbols: lists top-level definitions in a file. '
                            'code_action: list quick-fixes / refactors suggested by the '
                            'language server. Pass line+column to scope to one location, '
                            'or omit them to list actions for the whole file.'
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
