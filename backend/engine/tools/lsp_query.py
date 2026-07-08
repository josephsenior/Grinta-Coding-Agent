"""lsp tool — semantic code navigation via the language server.

Supports the following commands (all require an installed language server):
- ``find_definition``  locate where a symbol is defined
- ``find_references``  find all usages of a symbol
- ``hover``            read the docstring/type signature at a position
- ``list_symbols``     enumerate definitions in a file (``textDocument/documentSymbol``)
- ``get_diagnostics``  get errors/warnings for a file (after editing)

When no language server is installed for a file type the tool returns
``available=False``. Use ``find_symbols`` or ``grep`` for structure search instead.
Servers must be installed manually by the user — do not attempt to install
them yourself.
"""

from __future__ import annotations

from typing import Any

from backend.core.tools.tool_names import LSP_TOOL_NAME
from backend.ledger.action.code_nav import LspQueryAction


def create_lsp_query_tool(
    detected_servers: list[str] | None = None,
) -> dict[str, Any]:
    """Return the OpenAI function-calling tool definition for lsp.

    Args:
        detected_servers: Names of language servers actually detected on this
            host (e.g. ``['rust-analyzer', 'pylsp']``). Inlined into the
            description so the model does not need to cross-reference a
            separate System Capabilities block (which weak models lose track
            of in long prompts). When empty/None, a generic fallback is used.
    """
    servers = [s for s in (detected_servers or []) if s]
    if servers:
        detected_line = f'Detected on THIS host: {", ".join(servers)}.'
    else:
        detected_line = ''
    return {
        'type': 'function',
        'function': {
            'name': LSP_TOOL_NAME,
            'description': (
                'Read-only semantic code navigation via the locally-installed '
                'language server (LSP). Auto-detects servers on PATH (pyright, '
                f'pylsp, ruff, typescript-language-server, gopls, rust-analyzer, '
                f'clangd, …). {detected_line}\n'
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
                '  • File/symbol structure without a language server → use '
                '`find_symbols` or `grep`, not `lsp`.\n'
                '  • Edit code → use `replace_string` (exact text) or `multiedit` '
                '(batch). `lsp` is read-only and intentionally does not expose rename.\n'
                '  • Workspace-wide text/symbol search → use `grep` or `glob` '
                '(ripgrep). `list_symbols` only enumerates symbols in a single file.\n'
                '  • Code formatting / quick-fix application → run the project '
                'formatter or linter via `execute_bash` / `execute_powershell`.\n'
                'When no LSP server is installed this tool is hidden from the '
                'toolset entirely — its absence here means the user has at least '
                'one server on PATH. Do NOT attempt to install servers yourself; '
                'servers must be installed manually by the user.'
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
            f'Missing required argument "command" in tool call {LSP_TOOL_NAME}'
        )
    if not file:
        raise FunctionCallValidationError(
            f'Missing required argument "file" in tool call {LSP_TOOL_NAME}'
        )

    return LspQueryAction(
        file=file,
        command=command,
        line=int(arguments.get('line', 1)),
        column=int(arguments.get('column', 1)),
        symbol=str(arguments.get('symbol', '')),
    )
