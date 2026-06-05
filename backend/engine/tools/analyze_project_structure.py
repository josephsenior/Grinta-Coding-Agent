"""Project Map tool — gives the LLM a quick structural overview of the workspace.

Provides directory tree, import graph, symbol index, and recently modified files
in a single call, preventing cross-file breakage by surfacing dependencies the
LLM wouldn't otherwise know about.

This module is a thin shim that exposes the public tool definition and
top-level dispatcher. The per-mode helpers live in sibling modules:

  - backend.engine.tools._aps_shared             (run_command, _diag, imports-reverse)
  - backend.engine.tools._aps_tree               (tree + symbols modes)
  - backend.engine.tools._aps_file_modes         (imports + outline + recent + semantic)
  - backend.engine.tools._aps_callers_coverage   (callers + test_coverage modes)
  - backend.engine.tools._aps_dependencies       (dependencies mode)

Pure code motion: no logic changes.
"""

from __future__ import annotations

from collections.abc import Callable

from backend.engine.tools._aps_callers_coverage import (
    _build_callers_action,
    _build_test_coverage_action,
)
from backend.engine.tools._aps_dependencies import _build_dependencies_action
from backend.engine.tools._aps_file_modes import (
    _build_file_outline_action,
    _build_imports_action,
    _build_recent_action,
    _build_semantic_search_action,
)
from backend.engine.tools._aps_shared import _analyze_depth, _diag
from backend.engine.tools._aps_tree import _build_symbols_action, _build_tree_action
from backend.ledger.action import AgentThinkAction

ANALYZE_PROJECT_STRUCTURE_TOOL_NAME = 'analyze_project_structure'


def create_analyze_project_structure_tool() -> dict:
    """Return the OpenAI function-calling tool definition for analyze_project_structure."""
    return {
        'type': 'function',
        'function': {
            'name': ANALYZE_PROJECT_STRUCTURE_TOOL_NAME,
            'description': (
                'Get a structural overview of the project. '
                "Modes: 'tree' (directory tree with file sizes), "
                "'imports' (import/dependency graph for a file), "
                "'symbols' (classes, functions, top-level names in a file), "
                "'recent' (recently modified files in the repo), "
                "'callers' (find all files that reference a symbol/function), "
                "'test_coverage' (find test files that cover a given source file), "
                "'dependencies' (transitive upstream/downstream dependency tree for a file), "
                "'file_outline' (compact signatures for a source file — less context than a full read). "
                'Use this BEFORE multi-file edits to understand dependencies.'
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'command': {
                        'type': 'string',
                        'enum': [
                            'tree',
                            'imports',
                            'symbols',
                            'file_outline',
                            'recent',
                            'callers',
                            'test_coverage',
                            'semantic_search',
                            'dependencies',
                        ],
                        'description': (
                            'tree: directory tree (depth-limited). '
                            'imports: show what a file imports and what imports it (1 hop). '
                            'symbols: list classes/functions/top-level names in a file. '
                            'file_outline: AST signatures only (Python) or line-based heads (fallback) — '
                            'for large files before read. '
                            'recent: git log of recently modified files. '
                            'callers: find all files referencing a given symbol name. '
                            'test_coverage: find test files that likely test a given source file. '
                            'semantic_search: robust AST-based search for symbol references. '
                            'dependencies: transitive upstream/downstream dependency tree '
                            'for a file (multi-hop import graph, on-demand, no index).'
                        ),
                    },
                    'path': {
                        'type': 'string',
                        'description': (
                            "For 'tree': root directory to scan (default '.'). "
                            "For 'imports'/'symbols'/'file_outline'/'test_coverage'/'dependencies': "
                            'path to the file to analyze.'
                        ),
                        'default': '.',
                    },
                    'symbol': {
                        'type': 'string',
                        'description': (
                            "For 'callers': the symbol/function/class name to search for."
                        ),
                    },
                    'depth': {
                        'type': 'integer',
                        'description': (
                            "For 'tree': max depth (default 1). "
                            "For 'dependencies': max transitive hops (default 2, capped at 4)."
                        ),
                        'default': 1,
                    },
                    'direction': {
                        'type': 'string',
                        'enum': ['upstream', 'downstream', 'both'],
                        'description': (
                            "For 'dependencies': 'upstream' = files that import this one; "
                            "'downstream' = files this one imports; 'both' = union. Default 'both'."
                        ),
                        'default': 'both',
                    },
                },
                'required': ['command'],
            },
        },
    }


def build_analyze_project_structure_action(
    arguments: dict,
) -> AgentThinkAction:
    """Build the action for the analyze_project_structure tool call."""
    command = arguments.get('command', 'tree')
    path = arguments.get('path', '.')
    depth = _analyze_depth(arguments)

    if command == 'callers':
        if not (symbol := arguments.get('symbol', '')):
            return AgentThinkAction(
                thought=_diag(
                    reason="missing required parameter 'symbol'",
                    command='callers',
                    params={'path': path},
                    next_steps=[
                        "Re-call with symbol='<name>' (function or class to find references for).",
                        'Tip: pair with command=imports to first see what a file exports.',
                    ],
                )
            )
        return _build_callers_action(symbol, path)

    if command == 'semantic_search':
        if not (symbol := arguments.get('symbol', '')):
            return AgentThinkAction(
                thought=_diag(
                    reason="missing required parameter 'symbol'",
                    command='semantic_search',
                    params={'path': path},
                    next_steps=[
                        "Re-call with symbol='<name>' to AST-search for references.",
                    ],
                )
            )
        return _build_semantic_search_action(symbol, path)

    handlers: dict[str, Callable[[], AgentThinkAction]] = {
        'tree': lambda: _build_tree_action(path, depth),
        'imports': lambda: _build_imports_action(path),
        'symbols': lambda: _build_symbols_action(path),
        'file_outline': lambda: _build_file_outline_action(path),
        'recent': lambda: _build_recent_action(),
        'test_coverage': lambda: _build_test_coverage_action(path),
        'dependencies': lambda: _build_dependencies_action(
            path,
            depth=depth,
            direction=str(arguments.get('direction', 'both') or 'both'),
        ),
    }

    if command in handlers:
        return handlers[command]()

    return AgentThinkAction(
        thought=_diag(
            reason=f'unknown command {command!r}',
            command=command,
            params={'path': path, 'depth': depth},
            next_steps=[
                'Use one of: tree, imports, symbols, file_outline, recent, '
                'callers, test_coverage, semantic_search, dependencies.',
            ],
        )
    )
