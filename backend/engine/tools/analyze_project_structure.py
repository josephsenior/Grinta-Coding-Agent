"""Project Map tool — gives the LLM a quick structural overview of the workspace.

Provides directory tree, import graph, symbol index, and recently modified files
in a single call, preventing cross-file breakage by surfacing dependencies the
LLM wouldn't otherwise know about.

This module is a thin shim that exposes the public tool definition and
top-level dispatcher. The per-mode helpers live in sibling modules:

  - backend.engine.tools._aps_shared             (run_command, _diag, imports-reverse)
  - backend.engine.tools._aps_tree               (tree + symbols modes)
  - backend.engine.tools._aps_file_modes         (imports + outline + recent + semantic)
  - backend.engine.tools._aps_callers_coverage   (callers mode)
  - backend.engine.tools._aps_dependencies       (dependencies mode)

Pure code motion: no logic changes.
"""

from __future__ import annotations

from collections.abc import Callable

from backend.engine.tools._aps_callers_coverage import _build_callers_action
from backend.engine.tools._aps_dependencies import _build_dependencies_action
from backend.engine.tools._aps_file_modes import (
    _build_file_outline_action,
    _build_imports_action,
    _build_recent_action,
    _build_semantic_search_action,
)
from backend.engine.tools._aps_shared import _analyze_depth, _diag
from backend.engine.tools._aps_tree import _build_symbols_action, _build_tree_action
from backend.ledger.action.search import AnalyzeProjectStructureAction
from backend.ledger.observation.search import AnalyzeProjectStructureObservation

from backend.inference.tool_names import ANALYZE_PROJECT_STRUCTURE_TOOL_NAME


def create_analyze_project_structure_tool() -> dict:
    """Return the OpenAI function-calling tool definition for analyze_project_structure."""
    return {
        'type': 'function',
        'function': {
            'name': ANALYZE_PROJECT_STRUCTURE_TOOL_NAME,
            'description': (
                'Structural project overview — use when grep/glob/find_symbols are not enough. '
                "tree: directory tree; recent: git-modified files; "
                "imports/dependencies: import graph for a known file; "
                "symbols: per-file symbol list; file_outline: compact signatures only; "
                "callers: fast regex reference scan (prefer over semantic_search first); "
                "semantic_search: AST reference scan fallback. "
                'To find test files: use glob + grep (not this tool). '
                'Use BEFORE multi-file edits to understand dependencies.'
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
                            'semantic_search',
                            'dependencies',
                        ],
                        'description': (
                            'tree: directory tree (depth-limited). '
                            'imports: 1-hop import graph for a file. '
                            'symbols: per-file symbol list (file must be known). '
                            'file_outline: compact signatures only — large files before read. '
                            'recent: recently modified files via git. '
                            'callers: workspace-wide regex reference scan (default for references). '
                            'semantic_search: AST reference scan — use when callers misses or is ambiguous. '
                            'dependencies: transitive import graph for a file.'
                        ),
                    },
                    'path': {
                        'type': 'string',
                        'description': (
                            "For 'tree': root directory to scan (default '.'). "
                            "For 'imports'/'symbols'/'file_outline'/'dependencies': "
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
) -> AnalyzeProjectStructureAction:
    """Build the action for the analyze_project_structure tool call."""
    return AnalyzeProjectStructureAction(
        command=str(arguments.get('command', 'tree') or 'tree'),
        path=str(arguments.get('path', '.') or '.'),
        symbol=str(arguments.get('symbol', '') or ''),
        depth=_analyze_depth(arguments),
        direction=str(arguments.get('direction', 'both') or 'both'),
    )


def execute_analyze_project_structure(
    action: AnalyzeProjectStructureAction,
) -> AnalyzeProjectStructureObservation:
    """Execute an APS request and return a structured observation."""
    command = action.command
    path = action.path
    depth = action.depth

    if command == 'callers':
        if not action.symbol:
            return _make_aps_observation(
                action,
                _diag(
                    reason="missing required parameter 'symbol'",
                    command='callers',
                    params={'path': path},
                    next_steps=[
                        "Re-call with symbol='<name>' (function or class to find references for).",
                        'Tip: pair with command=imports to first see what a file exports.',
                    ],
                ),
            )
        return _make_aps_observation(action, _build_callers_action(action.symbol, path))

    if command == 'semantic_search':
        if not action.symbol:
            return _make_aps_observation(
                action,
                _diag(
                    reason="missing required parameter 'symbol'",
                    command='semantic_search',
                    params={'path': path},
                    next_steps=[
                        "Re-call with symbol='<name>' to AST-search for references.",
                    ],
                ),
            )
        return _make_aps_observation(
            action,
            _build_semantic_search_action(action.symbol, path),
        )

    handlers: dict[str, Callable[[], str]] = {
        'tree': lambda: _build_tree_action(path, depth),
        'imports': lambda: _build_imports_action(path),
        'symbols': lambda: _build_symbols_action(path),
        'file_outline': lambda: _build_file_outline_action(path),
        'recent': lambda: _build_recent_action(),
        'dependencies': lambda: _build_dependencies_action(
            path,
            depth=depth,
            direction=action.direction,
        ),
    }

    if command in handlers:
        return _make_aps_observation(action, handlers[command]())

    return _make_aps_observation(
        action,
        _diag(
            reason=f'unknown command {command!r}',
            command=command,
            params={'path': path, 'depth': depth},
            next_steps=[
                'Use one of: tree, imports, symbols, file_outline, recent, '
                'callers, semantic_search, dependencies.',
            ],
        )
    )


def _make_aps_observation(
    action: AnalyzeProjectStructureAction, content: str
) -> AnalyzeProjectStructureObservation:
    observation = AnalyzeProjectStructureObservation(
        content=content,
        command=action.command,
        path=action.path,
        symbol=action.symbol,
        depth=action.depth,
        direction=action.direction,
    )
    observation.tool_result = {
        'tool': ANALYZE_PROJECT_STRUCTURE_TOOL_NAME,
        'command': action.command,
        'path': action.path,
        'symbol': action.symbol,
        'depth': action.depth,
        'direction': action.direction,
    }
    return observation
