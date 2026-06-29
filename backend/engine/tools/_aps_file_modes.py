"""Per-file inspection modes for the analyze_project_structure tool.

Contains helpers and builders for the ``imports``, ``file_outline``,
``recent``, and ``semantic_search`` modes. These all read or scan a
single file (or a few files) and produce a textual report — distinct
from the tree/symbols/callers/dependencies modes that walk the
repository.

Extracted from ``backend.engine.tools.analyze_project_structure`` to
keep that module focused on the public tool API.
"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path

from backend.engine.tools._aps_shared import (
    _diag,
    _imports_reverse_via_rg,
    _imports_reverse_via_walk,
    _run_command,
)


def _imports_forward_block(path: str) -> list[str]:
    """Lines describing import/from statements in ``path`` (lines only)."""
    out: list[str] = []
    if os.path.isfile(path):
        try:
            with open(path, encoding='utf-8', errors='ignore') as f:
                for i, line in enumerate(f, 1):
                    if line.startswith('import ') or line.startswith('from '):
                        out.append(f'{i}:{line.rstrip()}')
        except Exception as e:
            out.append(f'(error reading file: {e})')
    else:
        out.append('(file not found)')
    return out


def _build_imports_action(path: str) -> str:
    """Show what a file imports AND what other files import it."""
    out = [f'=== IMPORTS IN {os.path.basename(path)} ===']
    out.extend(_imports_forward_block(path))
    out.append('')
    out.append('=== FILES THAT IMPORT THIS MODULE ===')
    basename = os.path.splitext(os.path.basename(path))[0]

    rg_hits = _imports_reverse_via_rg(basename)
    if rg_hits is not None:
        out.extend(rg_hits)
        return '\n'.join(out)

    walk_hits = _imports_reverse_via_walk(basename)
    if walk_hits:
        out.extend(walk_hits)
    else:
        out.append(
            _diag(
                reason='no other files import this module',
                command='imports',
                params={'path': path, 'basename_searched': basename},
                next_steps=[
                    'Confirm the file path is correct and committed to the repo.',
                    'Try command=callers with a public symbol name from this file.',
                    'Try the `grep` tool (separate tool) for non-import references.',
                ],
            )
        )
    return '\n'.join(out)


def _ast_func_outline_signature(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    indent: str,
) -> str:
    pref = 'async def' if isinstance(node, ast.AsyncFunctionDef) else 'def'
    try:
        args_s = ast.unparse(node.args)
    except Exception:
        args_s = '(...)'
    ret = ''
    if node.returns is not None:
        try:
            ret = ' -> ' + ast.unparse(node.returns)
        except Exception:
            ret = ' -> ...'
    return f'{indent}{pref} {node.name}{args_s}{ret}'


def _outline_append_assign_targets(node: ast.Assign) -> list[str]:
    lines: list[str] = []
    for t in node.targets:
        if isinstance(t, ast.Name) and not t.id.startswith('_'):
            try:
                lines.append(f'{t.id} = …')
            except Exception:
                lines.append('(assignment)')
            break
    return lines


def _outline_class_body_lines(
    class_node: ast.ClassDef, start_count: int, max_lines: int
) -> tuple[list[str], int]:
    out: list[str] = [f'class {class_node.name}']
    count = start_count + 1
    for item in class_node.body:
        if count >= max_lines:
            break
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if item.name.startswith('__') and item.name not in (
                '__init__',
                '__new__',
            ):
                continue
            out.append(_ast_func_outline_signature(item, '  '))
            count += 1
    return out, count


def _python_outline_lines_from_ast(
    tree: ast.Module,
    *,
    max_lines: int = 200,
) -> list[str]:
    """Outline body lines after header for parsed Python (may truncate)."""
    out: list[str] = []
    count = 0
    for node in tree.body:
        if count >= max_lines:
            out.append('… (truncated)')
            break
        if isinstance(node, ast.ClassDef):
            cls_lines, count = _outline_class_body_lines(node, count, max_lines)
            out.extend(cls_lines)
            continue

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith('_'):
                out.append(_ast_func_outline_signature(node, ''))
                count += 1
            continue

        if isinstance(node, ast.Assign):
            assign_lines = _outline_append_assign_targets(node)
            out.extend(assign_lines)
            if assign_lines:
                count += 1
            continue

    return out


def _file_outline_fallback_lines(path: str) -> list[str]:
    """Non-Python: first line of each plausible definition (regex), capped."""
    sym_re = re.compile(r'^(class |def |async def |[A-Z_][A-Z_0-9]* *=)')
    lines_out: list[str] = []
    try:
        with open(path, encoding='utf-8', errors='ignore') as f:
            for i, line in enumerate(f, 1):
                if sym_re.match(line):
                    lines_out.append(f'{i}:{line.rstrip()}')
                    if len(lines_out) >= 80:
                        lines_out.append('… (truncated)')
                        break
    except OSError as e:
        return [f'(error reading file: {e})']
    if not lines_out:
        lines_out.append('(no outline heads found — use symbols or read)')
    return lines_out


def _build_file_outline_action(path: str) -> str:
    """Compact API-style outline: Python AST signatures, else line-based heads."""
    base = os.path.basename(path)
    out: list[str] = [f'=== FILE OUTLINE: {base} ===']
    if not os.path.isfile(path):
        out.append(
            _diag(
                reason='file not found at given path',
                command='file_outline',
                params={'path': path},
                next_steps=[
                    'Pass a path relative to the workspace root.',
                    'Run command=tree first to discover the actual file location.',
                ],
            )
        )
        return '\n'.join(out)

    if path.endswith('.py'):
        try:
            src = Path(path).read_text(encoding='utf-8', errors='ignore')
            tree = ast.parse(src)
        except (OSError, SyntaxError, ValueError) as e:
            out.append(f'(could not parse Python AST: {e}; falling back to line heads)')
            return '\n'.join(out + _file_outline_fallback_lines(path))

        out.extend(_python_outline_lines_from_ast(tree))
        if len(out) <= 1:
            out.append(
                _diag(
                    reason='no top-level definitions in file',
                    command='file_outline',
                    params={'path': path},
                    next_steps=[
                        'Use command=symbols for a regex-based listing.',
                        'Use read directly — the file may be small or data-only.',
                    ],
                )
            )
        return '\n'.join(out)

    out.extend(_file_outline_fallback_lines(path))
    return '\n'.join(out)


def _build_recent_action() -> str:
    """Recently modified files via git log."""
    out = ['=== RECENTLY MODIFIED FILES (last 20 commits) ===']
    try:
        res = _run_command(
            ['git', 'log', '--oneline', '--name-only', '-20', '--pretty=format:%h %s'],
            process_timeout=10.0,
        )
        if res.stdout.strip():
            lines = res.stdout.splitlines()
            if len(lines) > 100:
                lines = lines[:100] + ['… (truncated)']
            out.extend(lines)
        else:
            out.append(
                _diag(
                    reason='no commits or current directory is not a git repository',
                    command='recent',
                    params={'cwd': os.getcwd()},
                    next_steps=[
                        'Run from inside a git repository, or skip command=recent.',
                        'Use command=tree for a directory listing instead.',
                    ],
                )
            )
    except Exception:
        out.append('(git not available or error running git)')
    return '\n'.join(out)


def _build_semantic_search_action(symbol: str, path: str) -> str:
    """Robust AST-based reference search using the semantic_analyzer script."""
    import sys

    import backend.engine.tools.semantic_analyzer as sa

    script_path = sa.__file__
    try:
        res = _run_command(
            [sys.executable, script_path, 'find_references', symbol, path],
            process_timeout=30.0,
        )
        return (
            res.stdout
            if res.stdout.strip()
            else _diag(
                reason='AST search returned no output',
                command='semantic_search',
                params={'symbol': symbol, 'path': path},
                next_steps=[
                    'Confirm path points to a parseable source file.',
                    'Try command=callers for a faster regex-based scan.',
                ],
            )
        )
    except Exception as e:
        return f'(error running semantic search: {e})'
