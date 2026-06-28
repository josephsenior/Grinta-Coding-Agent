"""Tests for DAP adapter spawn helpers."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from backend.execution.dap._dap_spawn_utils import (
    format_adapter_spawn_error,
    resolve_adapter_cwd,
    resolve_python_executable,
    uses_python_debugpy_adapter,
    validate_debugger_start,
)
from backend.execution.dap._dap_errors import DAPError
from backend.ledger.action.debugger import DebuggerAction


def test_resolve_python_executable_prefers_existing_file(tmp_path: Path) -> None:
    py = tmp_path / 'python.exe'
    py.write_text('', encoding='utf-8')
    assert resolve_python_executable(str(py)) == str(py.resolve())


def test_resolve_adapter_cwd_falls_back_when_missing(tmp_path: Path) -> None:
    missing = tmp_path / 'missing'
    fallback = tmp_path / 'workspace'
    fallback.mkdir()
    assert resolve_adapter_cwd(missing, fallback=fallback) == str(fallback.resolve())


def test_format_adapter_spawn_error_winerror_267_mentions_cwd() -> None:
    exc = OSError('directory invalid')
    exc.winerror = 267  # type: ignore[attr-defined]
    message = format_adapter_spawn_error(
        exc,
        command=[sys.executable, '-m', 'debugpy.adapter'],
        cwd=r'C:\missing\workspace',
    )
    assert 'cwd is invalid' in message
    assert 'Python path' not in message


def test_format_adapter_spawn_error_file_not_found_mentions_python() -> None:
    exc = FileNotFoundError(2, 'missing', r'C:\no\python.exe')
    message = format_adapter_spawn_error(
        exc,
        command=[r'C:\no\python.exe', '-m', 'debugpy.adapter'],
        cwd=str(Path.cwd()),
    )
    assert 'Python path' in message
    assert 'debugpy' in message


def test_validate_debugger_start_rejects_non_python_program(tmp_path: Path) -> None:
    bad_program = 'sample.txt'
    action = DebuggerAction(
        debug_action='start',
        adapter='python',
        program=bad_program,
    )
    with pytest.raises(DAPError, match='not a Python file'):
        validate_debugger_start(
            action, adapter='python', workspace_root=tmp_path
        )


def test_validate_debugger_start_rejects_missing_program(tmp_path: Path) -> None:
    action = DebuggerAction(
        debug_action='start',
        adapter='python',
        program='missing.py',
    )
    with pytest.raises(DAPError, match='does not exist'):
        validate_debugger_start(
            action, adapter='python', workspace_root=tmp_path
        )


def test_uses_python_debugpy_adapter_for_py_program_without_adapter() -> None:
    action = DebuggerAction(debug_action='start', program='app.py')
    assert uses_python_debugpy_adapter(action, 'python') is True
    assert uses_python_debugpy_adapter(action, None) is True
    assert uses_python_debugpy_adapter(action, 'node') is False
