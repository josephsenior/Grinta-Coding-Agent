"""Helpers for spawning DAP adapter subprocesses reliably on all platforms."""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from backend.execution.dap._dap_errors import DAPError

_PYTHON_ADAPTERS = frozenset({'python', 'debugpy'})
_PYTHON_PROGRAM_SUFFIXES = frozenset({'.py', '.pyw'})


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


def _debugpy_importable() -> bool:
    try:
        return importlib.util.find_spec('debugpy.adapter') is not None
    except (ImportError, ValueError):
        return False


def uses_python_debugpy_adapter(action: Any, adapter: str | None) -> bool:
    """Return True when start would spawn the built-in ``debugpy`` preset."""
    if getattr(action, 'adapter_command', None):
        return False
    normalized = (adapter or '').strip().lower()
    if normalized in _PYTHON_ADAPTERS:
        return True
    language = str(getattr(action, 'language', '') or '').strip().lower()
    if language == 'python':
        return True
    program = str(getattr(action, 'program', '') or '').strip()
    if program and Path(program).suffix.lower() in _PYTHON_PROGRAM_SUFFIXES:
        return not normalized or normalized in _PYTHON_ADAPTERS
    return False


def _resolve_program_path(program: str, workspace_root: str | Path) -> Path:
    path = Path(program)
    if path.is_absolute():
        return path
    return Path(workspace_root) / path


def validate_debugger_start(
    action: Any,
    *,
    adapter: str | None,
    workspace_root: str | Path,
) -> None:
    """Reject obviously invalid Python debugger launches before spawning debugpy."""
    request = str(getattr(action, 'request', 'launch') or 'launch').strip().lower()
    if request != 'launch':
        return
    if not uses_python_debugpy_adapter(action, adapter):
        return

    if not _debugpy_importable():
        raise DAPError(
            'debugpy is not installed in the active Python environment. '
            'Install it with: pip install debugpy'
        )

    program = str(getattr(action, 'program', '') or '').strip()
    if not program:
        raise DAPError(
            "debugger start with the Python adapter requires `program` "
            'pointing to an existing .py or .pyw file'
        )

    suffix = Path(program).suffix.lower()
    if suffix not in _PYTHON_PROGRAM_SUFFIXES:
        raise DAPError(
            f'debugger program {program!r} is not a Python file '
            f'(expected .py or .pyw, got {suffix!r}). '
            'Use a valid Python script or choose a different adapter.'
        )

    resolved = _resolve_program_path(program, workspace_root)
    if not resolved.is_file():
        raise DAPError(f'debugger program does not exist: {resolved}')
