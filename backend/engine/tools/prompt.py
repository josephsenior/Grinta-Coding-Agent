"""Helpers for adapting tool prompts to the active terminal runtime."""

from __future__ import annotations

import base64
import functools
import sys
from contextvars import ContextVar
from typing import Any

_active_tool_registry: ContextVar[Any | None] = ContextVar(
    'active_tool_registry', default=None
)
# Worker threads (e.g. Orchestrator.step ThreadPoolExecutor) do not inherit
# ContextVar values; mirror the active registry here so tool command generation
# matches the same ToolRegistry as SessionManager / create_shell_session.
_registry_for_process: Any | None = None


def set_active_tool_registry(registry: Any | None) -> None:
    """Bind the ToolRegistry used by ``SessionManager`` / ``create_shell_session``.

    When set (from :class:`~backend.execution.action_execution_server.RuntimeExecutor`
    startup), :func:`uses_powershell_terminal` reads ``registry.has_bash`` so generated
    shell command strings match the actual shell (Git Bash vs PowerShell).
    """
    global _registry_for_process
    _registry_for_process = registry
    _active_tool_registry.set(registry)


def get_active_tool_registry() -> Any | None:
    """Return the registry installed by :func:`set_active_tool_registry`, if any."""
    ctx = _active_tool_registry.get()
    if ctx is not None:
        return ctx
    return _registry_for_process


@functools.cache
def _get_global_tool_registry() -> Any:
    from backend.execution.utils.tool_registry import ToolRegistry

    return ToolRegistry()


def _runtime_prefers_powershell() -> bool:
    """Mirror runtime shell-session selection for prompt-side tool generation."""
    active = get_active_tool_registry()
    if active is not None:
        return not active.has_bash
    registry = _get_global_tool_registry()
    return not registry.has_bash


def uses_powershell_terminal() -> bool:
    """Return True when the active terminal contract should be PowerShell.

    Aligns with ``create_shell_session()`` by asking the same ToolRegistry-
    based question the runtime uses on Windows: prefer bash when available,
    otherwise fall back to PowerShell.
    """
    if not sys.platform.lower().startswith('win'):
        return False
    return _runtime_prefers_powershell()


def get_shell_name() -> str:
    """Return the shell name that matches the runtime terminal contract."""
    return 'powershell' if uses_powershell_terminal() else 'bash'


def is_windows_with_bash() -> bool:
    """True when running on Windows but using Git Bash as the active shell."""
    return sys.platform == 'win32' and not uses_powershell_terminal()


def get_python_shell_command() -> str:
    """Return the preferred Python executable for the active shell contract."""
    if uses_powershell_terminal():
        return 'python'
    return 'python3'


def build_python_exec_command(script: str) -> str:
    """Return a shell-safe Python command that executes a base64-encoded script."""
    encoded = base64.b64encode(script.encode()).decode()
    py_expr = f"import base64;exec(base64.b64decode(b'{encoded}').decode())"

    if uses_powershell_terminal():
        return f'python -c "{py_expr}"'

    return (
        "if command -v python3 >/dev/null 2>&1; then "
        f"python3 -c \"{py_expr}\"; "
        "elif command -v python >/dev/null 2>&1; then "
        f"python -c \"{py_expr}\"; "
        "elif command -v py >/dev/null 2>&1; then "
        f"py -3 -c \"{py_expr}\"; "
        "else echo '[MISSING_TOOL] python/python3/py not found in PATH'; exit 127; fi"
    )


def get_terminal_tool_name() -> str:
    """Return the terminal tool name that matches the runtime shell."""
    return 'execute_powershell' if uses_powershell_terminal() else 'execute_bash'
