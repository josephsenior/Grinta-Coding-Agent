"""Callers mode for the analyze_project_structure tool.

Contains helpers and builders for the ``callers`` mode (find all files
referencing a symbol). Walks the repository to locate matching files.

Extracted from ``backend.engine.tools.analyze_project_structure`` to
keep that module focused on the public tool API.
"""

from __future__ import annotations

import os
import re
import shutil

from backend.engine.tools._aps_shared import _diag, _run_command
from backend.engine.tools.ignore_filter import (
    get_ignore_spec,
    is_ignored_file,
    prune_ignored_dirs,
)


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
            lines = res.stdout.splitlines()
            if len(lines) > 50:
                return lines[:50] + ['… (truncated)']
            return lines
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


def _build_callers_action(symbol: str, scope: str) -> str:
    """Find all files that reference a given symbol (function, class, variable)."""
    from backend.utils.impact_analysis import analyze_symbol_impact

    safe_scope = scope if scope and scope != '.' else '.'
    report = analyze_symbol_impact(safe_scope, symbol)

    if report is None or report.total_references == 0:
        trunc_sym = f'{symbol[:40]}…' if len(symbol) > 40 else symbol
        return _diag(
            reason=f'no references found for symbol {trunc_sym!r}',
            command='callers',
            params={'symbol': symbol, 'path': scope},
            next_steps=[
                'Verify the symbol name is spelled exactly as in source.',
                'Try command=semantic_search for AST-aware matching.',
                'Broaden the search by passing path=. (workspace root).',
            ],
        )

    trunc_sym = f'{symbol[:40]}…' if len(symbol) > 40 else symbol
    out = [
        f'=== REFERENCES TO {trunc_sym} ===',
        f'Engine: {report.engine.upper()}',
        f'Confidence: {report.confidence}',
        f'References: {report.total_references} across {report.unique_files} files',
        f'Production: {report.production_references}',
        f'Tests: {report.test_references}',
        f'Outside definition file: {report.external_file_references}',
        f'Estimated impact: {report.risk.upper()}',
    ]
    if report.reasons:
        out.append('Reasons:')
        for reason in report.reasons:
            out.append(f'- {reason}')

    out.append('\nLocations:')
    for loc in report.locations:
        out.append(f'  {loc.file_path}:{loc.line}: {loc.text}')
    if report.truncated:
        out.append('  … (truncated)')

    return '\n'.join(out)
