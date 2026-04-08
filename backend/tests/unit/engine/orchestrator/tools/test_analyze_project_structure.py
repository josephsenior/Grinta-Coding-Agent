"""Unit tests for backend.engine.tools.analyze_project_structure."""

from __future__ import annotations

from backend.engine.tools import analyze_project_structure
from backend.ledger.action import CmdRunAction


def test_tree_action_uses_powershell_fallback_on_windows_without_bash(
    monkeypatch,
) -> None:
    monkeypatch.setattr(analyze_project_structure, 'uses_powershell_terminal', lambda: True)

    action = analyze_project_structure.build_analyze_project_structure_action(
        {'command': 'tree', 'path': '.', 'depth': 2}
    )

    assert isinstance(action, CmdRunAction)
    assert 'Get-ChildItem' in action.command
    assert 'if command -v tree' not in action.command
    assert 'find ' not in action.command


def test_tree_action_keeps_posix_command_when_bash_is_available(
    monkeypatch,
) -> None:
    monkeypatch.setattr(analyze_project_structure, 'uses_powershell_terminal', lambda: False)

    action = analyze_project_structure.build_analyze_project_structure_action(
        {'command': 'tree', 'path': '.', 'depth': 2}
    )

    assert isinstance(action, CmdRunAction)
    assert 'if command -v tree' in action.command
    assert 'Get-ChildItem' not in action.command


# ------------------------------------------------------------------ #
#  PowerShell branch tests for non-tree modes
# ------------------------------------------------------------------ #


def test_imports_action_uses_powershell_on_windows(monkeypatch) -> None:
    monkeypatch.setattr(analyze_project_structure, 'uses_powershell_terminal', lambda: True)
    action = analyze_project_structure.build_analyze_project_structure_action(
        {'command': 'imports', 'path': 'foo/bar.py'}
    )
    assert isinstance(action, CmdRunAction)
    assert 'Select-String' in action.command
    assert 'grep' not in action.command
    assert 'basename' not in action.command


def test_imports_action_uses_bash_when_available(monkeypatch) -> None:
    monkeypatch.setattr(analyze_project_structure, 'uses_powershell_terminal', lambda: False)
    action = analyze_project_structure.build_analyze_project_structure_action(
        {'command': 'imports', 'path': 'foo/bar.py'}
    )
    assert isinstance(action, CmdRunAction)
    assert 'grep' in action.command


def test_symbols_action_uses_powershell_on_windows(monkeypatch) -> None:
    monkeypatch.setattr(analyze_project_structure, 'uses_powershell_terminal', lambda: True)
    action = analyze_project_structure.build_analyze_project_structure_action(
        {'command': 'symbols', 'path': 'foo/bar.py'}
    )
    assert isinstance(action, CmdRunAction)
    assert 'Select-String' in action.command
    assert 'grep' not in action.command


def test_callers_action_uses_powershell_on_windows(monkeypatch) -> None:
    monkeypatch.setattr(analyze_project_structure, 'uses_powershell_terminal', lambda: True)
    action = analyze_project_structure.build_analyze_project_structure_action(
        {'command': 'callers', 'symbol': 'my_func', 'path': '.'}
    )
    assert isinstance(action, CmdRunAction)
    cmd = action.command
    assert 'Get-Command rg' in cmd or 'Select-String' in cmd
    assert 'grep' not in cmd


def test_test_coverage_action_uses_powershell_on_windows(monkeypatch) -> None:
    monkeypatch.setattr(analyze_project_structure, 'uses_powershell_terminal', lambda: True)
    action = analyze_project_structure.build_analyze_project_structure_action(
        {'command': 'test_coverage', 'path': 'backend/engine/planner.py'}
    )
    assert isinstance(action, CmdRunAction)
    cmd = action.command
    assert 'Get-ChildItem' in cmd
    assert 'find ' not in cmd
    assert 'basename' not in cmd
    assert 'dirname' not in cmd


def test_recent_action_uses_powershell_on_windows(monkeypatch) -> None:
    monkeypatch.setattr(analyze_project_structure, 'uses_powershell_terminal', lambda: True)
    action = analyze_project_structure.build_analyze_project_structure_action(
        {'command': 'recent'}
    )
    assert isinstance(action, CmdRunAction)
    assert 'Write-Output' in action.command
    assert 'echo ' not in action.command.lower().split('write-output')[0]