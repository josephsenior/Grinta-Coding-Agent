"""Shared helpers for the analyze_project_structure tool.

Small utilities used by multiple mode-specific helpers: the bounded
subprocess wrapper, the diagnostic block renderer, the depth parser,
and the reverse-import search (used by both the imports and
dependencies modes).

Extracted from ``backend.engine.tools.analyze_project_structure`` to
keep that module focused on the public tool API.
"""

from __future__ import annotations

import os
import re
import shutil
from typing import Any

from backend.core.bounded_result import BoundedResult
from backend.engine.tools.ignore_filter import (
    get_ignore_spec,
    is_ignored_file,
    prune_ignored_dirs,
)
from backend.utils.async_helpers.subprocess_bridge import run_bounded_subprocess_sync


def _run_command(
    args: list[str],
    *,
    cwd: str | None = None,
    process_timeout: float = 30.0,
    max_bytes_per_stream: int = 2 * 1024 * 1024,
) -> BoundedResult:
    return run_bounded_subprocess_sync(
        args,
        cwd=cwd,
        process_timeout=process_timeout,
        max_bytes_per_stream=max_bytes_per_stream,
    )


def _analyze_depth(arguments: dict) -> int:
    try:
        return int(arguments.get('depth', 1))
    except (ValueError, TypeError):
        return 1


def _diag(
    *,
    reason: str,
    command: str,
    params: dict[str, Any] | None = None,
    next_steps: list[str] | None = None,
) -> str:
    """Render a structured diagnostic block for empty/missing-input results.

    Replaces opaque ``"(no symbols found)"`` style messages with a small
    block that tells the model *why* the result was empty, *what arguments*
    it actually used, and *what to try next*. The shape is stable enough
    for downstream agents to scan but still human-readable.
    """
    lines: list[str] = ['[ANALYZE_PROJECT_STRUCTURE] no_results']
    lines.append(f'  command: {command}')
    lines.append(f'  reason: {reason}')
    if params:
        flat = ', '.join(
            f'{k}={v!r}' for k, v in params.items() if v is not None and v != ''
        )
        if flat:
            lines.append(f'  params_used: {flat}')
    if next_steps:
        lines.append('  next_steps:')
        for step in next_steps:
            lines.append(f'    - {step}')
    return '\n'.join(lines)


def _imports_reverse_via_rg(basename: str) -> list[str] | None:
    """Return importer paths from ripgrep when it finds hits; otherwise ``None``."""
    rg = shutil.which('rg')
    if not rg:
        return None
    try:
        res = _run_command(
            [
                rg,
                '-l',
                f'(import|from).*{basename}',
                '--type',
                'py',
                '--glob',
                '!__pycache__',
            ],
        )
        if res.stdout.strip():
            return res.stdout.splitlines()[:30]
    except Exception:
        pass
    return None


def _imports_reverse_via_walk(basename: str) -> list[str]:
    """Python traversal fallback for reverse-import search."""
    import_re = re.compile(f'(import|from).*{re.escape(basename)}')
    root = os.getcwd()
    spec = get_ignore_spec(root)
    lines: list[str] = []
    count = 0
    for root_dir, dirs, files in os.walk('.'):
        prune_ignored_dirs(root, root_dir, dirs, spec)

        for f in files:
            if f.endswith('.py'):
                if is_ignored_file(root, root_dir, f, spec):
                    continue
                fpath = os.path.join(root_dir, f)
                try:
                    with open(fpath, encoding='utf-8', errors='ignore') as fl:
                        if import_re.search(fl.read()):
                            lines.append(fpath)
                            count += 1
                            if count >= 30:
                                break
                except Exception:
                    pass
            if count >= 30:
                break
        if count >= 30:
            break
    return lines
