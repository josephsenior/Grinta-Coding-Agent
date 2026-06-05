"""Callers and test-coverage modes for the analyze_project_structure tool.

Contains helpers and builders for the ``callers`` (find all files
referencing a symbol) and ``test_coverage`` (find test files that
likely cover a given source file) modes. Both walk the repository
to locate matching files.

Extracted from ``backend.engine.tools.analyze_project_structure`` to
keep that module focused on the public tool API.
"""

from __future__ import annotations

import os
import re
import shutil
from collections.abc import Callable
from typing import Any

from backend.engine.tools._aps_shared import _diag, _run_command
from backend.engine.tools.ignore_filter import (
    get_ignore_spec,
    is_ignored_file,
    prune_ignored_dirs,
)
from backend.ledger.action import AgentThinkAction


def _callers_lines_via_rg(symbol: str, safe_scope: str) -> list[str] | None:
    """Return rg output lines only when rg finds matches."""
    rg = shutil.which('rg')
    if not rg:
        return None
    try:
        res = _run_command(
            [
                rg,
                '-n',
                '--word-regexp',
                symbol,
                '--type',
                'py',
                '--type',
                'js',
                '--type',
                'ts',
                '--glob',
                '!__pycache__',
                '--glob',
                '!node_modules',
                '--glob',
                '!.git',
                safe_scope,
            ],
        )
        if res.stdout.strip():
            return res.stdout.splitlines()[:50]
    except Exception:
        pass
    return None


def _gather_caller_hits_in_file(
    fpath: str,
    sym_re: re.Pattern[str],
    lines: list[str],
    count: int,
    *,
    limit: int = 50,
) -> int:
    """Append matches from ``fpath`` until ``limit`` total hits."""
    try:
        with open(fpath, encoding='utf-8', errors='ignore') as fl:
            for i, line in enumerate(fl, 1):
                if sym_re.search(line):
                    lines.append(f'{fpath}:{i}:{line.rstrip()}')
                    count += 1
                    if count >= limit:
                        return count
    except Exception:
        pass
    return count


def _callers_lines_via_walk(
    *,
    symbol: str,
    safe_scope: str,
) -> tuple[list[str], int]:
    """Walk files for symbol references."""
    sym_re = re.compile(r'\b' + re.escape(symbol) + r'\b')
    lines: list[str] = []
    count = 0
    root = os.path.abspath('.')
    spec = get_ignore_spec(root)
    for root_dir, dirs, files in os.walk(safe_scope):
        prune_ignored_dirs(root, root_dir, dirs, spec)

        for f in files:
            if is_ignored_file(root, root_dir, f, spec):
                continue
            if f.endswith(('.py', '.js', '.ts', '.tsx', '.jsx')):
                fpath = os.path.join(root_dir, f)
                count = _gather_caller_hits_in_file(fpath, sym_re, lines, count)
                if count >= 50:
                    break
            if count >= 50:
                break
        if count >= 50:
            break
    return lines, count


def _build_callers_action(symbol: str, scope: str) -> AgentThinkAction:
    """Find all files that reference a given symbol (function, class, variable)."""
    trunc_sym = f'{symbol[:40]}…' if len(symbol) > 40 else symbol
    out = [f'=== CALLERS OF {trunc_sym} ===']

    safe_scope = scope if scope and scope != '.' else '.'
    rg_lines = _callers_lines_via_rg(symbol, safe_scope)
    if rg_lines is not None:
        out.extend(rg_lines)
        return AgentThinkAction(thought='\n'.join(out))

    walk_lines, count = _callers_lines_via_walk(
        symbol=symbol,
        safe_scope=safe_scope,
    )
    out.extend(walk_lines)
    if count == 0:
        out.append(
            _diag(
                reason=f'no references found for symbol {trunc_sym!r}',
                command='callers',
                params={'symbol': symbol, 'path': scope},
                next_steps=[
                    'Verify the symbol name is spelled exactly as in source.',
                    'Try command=semantic_search for AST-aware matching.',
                    'Broaden the search by passing path=. (workspace root).',
                ],
            )
        )
    return AgentThinkAction(thought='\n'.join(out))


def _collect_matching_files(
    start_dir: str,
    *,
    root: str,
    spec: Any,
    limit: int,
    predicate: Callable[[str, str, str], bool],
) -> list[str]:
    matches: list[str] = []
    for root_dir, dirs, files in os.walk(start_dir):
        prune_ignored_dirs(root, root_dir, dirs, spec)
        for filename in files:
            if is_ignored_file(root, root_dir, filename, spec):
                continue
            fpath = os.path.join(root_dir, filename)
            if not predicate(root_dir, filename, fpath):
                continue
            matches.append(fpath)
            if len(matches) >= limit:
                return matches
    return matches


def _file_contains_pattern(fpath: str, pattern: re.Pattern[str]) -> bool:
    try:
        with open(fpath, encoding='utf-8', errors='ignore') as file_handle:
            return bool(pattern.search(file_handle.read()))
    except Exception:
        return False


def _extend_named_section(
    out: list[str],
    *,
    title: str,
    items: list[str],
    empty_message: str,
) -> None:
    out.append(title)
    out.extend(items)
    if not items:
        out.append(empty_message)
    out.append('')


def _build_test_coverage_action(path: str) -> AgentThinkAction:
    """Find test files that likely cover a given source file."""
    basename = os.path.splitext(os.path.basename(path))[0]
    dirname = os.path.dirname(path) or '.'
    out = [f'=== TEST COVERAGE FOR {os.path.basename(path)} ===']

    root = os.path.abspath('.')
    spec = get_ignore_spec(root)

    name_re = re.compile(
        rf'^(test_{re.escape(basename)}\.py|{re.escape(basename)}_test\.py)$'
    )
    test_files = _collect_matching_files(
        '.',
        root=root,
        spec=spec,
        limit=20,
        predicate=lambda _root_dir, filename, _fpath: bool(name_re.match(filename)),
    )
    _extend_named_section(
        out,
        title='--- Tests by naming convention ---',
        items=test_files,
        empty_message='(none)',
    )

    import_re = re.compile(rf'(import|from).*{re.escape(basename)}')
    import_test_files = _collect_matching_files(
        '.',
        root=root,
        spec=spec,
        limit=20,
        predicate=lambda _root_dir, filename, fpath: (
            (filename.startswith('test_') or filename.endswith('_test.py'))
            and fpath not in test_files
            and _file_contains_pattern(fpath, import_re)
        ),
    )
    _extend_named_section(
        out,
        title='--- Tests that import this module ---',
        items=import_test_files,
        empty_message='(no importing test files found)',
    )

    conftest_files = _collect_matching_files(
        dirname,
        root=root,
        spec=spec,
        limit=10,
        predicate=lambda _root_dir, filename, _fpath: filename == 'conftest.py',
    )
    _extend_named_section(
        out,
        title='--- Conftest files in scope ---',
        items=conftest_files,
        empty_message='(none)',
    )

    return AgentThinkAction(thought='\n'.join(out))
