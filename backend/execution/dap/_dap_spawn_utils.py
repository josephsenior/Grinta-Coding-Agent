"""Helpers for spawning DAP adapter subprocesses reliably on all platforms."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def resolve_python_executable(explicit: str | None = None) -> str:
    """Return a Python executable that exists and can launch ``debugpy.adapter``."""
    candidates: list[str] = []
    if explicit:
        candidates.append(explicit)
    candidates.append(sys.executable)
    candidates.append(shutil.which('python') or '')
    candidates.append(shutil.which('python3') or '')
    try:
        from backend.core.os_capabilities import OS_CAPS

        candidates.append(shutil.which(OS_CAPS.default_python_exec) or '')
    except Exception:
        pass

    seen: set[str] = set()
    for candidate in candidates:
        candidate = candidate.strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        path = Path(candidate)
        if path.is_file():
            return str(path.resolve())
    return sys.executable


def resolve_adapter_cwd(
    cwd: str | Path | None,
    *,
    fallback: str | Path | None = None,
) -> str:
    """Return an existing directory suitable for ``subprocess.Popen(..., cwd=...)``."""
    for candidate in (cwd, fallback, os.getcwd()):
        if candidate is None:
            continue
        path = Path(candidate)
        try:
            if path.is_dir():
                return str(path.resolve())
        except OSError:
            continue
    return os.getcwd()


def format_adapter_spawn_error(
    exc: OSError,
    *,
    command: list[str],
    cwd: str | None,
) -> str:
    """Explain spawn failures without mislabeling invalid ``cwd`` as missing Python."""
    winerror = getattr(exc, 'winerror', None)
    argv0 = command[0] if command else '<empty>'
    if winerror == 267:
        return (
            f'DAP adapter cwd is invalid ({cwd!r}): {exc}. '
            'Use an existing workspace directory for debugger start.'
        )
    if isinstance(exc, FileNotFoundError) or winerror == 2:
        return (
            f'The configured Python path {argv0!r} does not exist ({exc}). '
            'The debugger cannot spawn a DAP adapter. '
            'Fix: install Python/debugpy in the active environment or pass a valid '
            '`python` argument to the debugger tool.'
        )
    return f'Failed to start DAP adapter {argv0!r} (cwd={cwd!r}): {exc}'
