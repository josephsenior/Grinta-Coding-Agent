from __future__ import annotations

from backend.engine.tools import search_code as search_code_mod
from backend.engine.tools.search_code import build_search_code_action


class TestBuildSearchCodeAction:
    def test_search_mode_excludes_generated_dirs_for_rg_and_grep(self, monkeypatch) -> None:
        monkeypatch.setattr(search_code_mod, 'uses_powershell_terminal', lambda: False)
        action = build_search_code_action(pattern='show_grinta_splash')

        assert '--glob=!**/.mypy_cache/**' in action.command
        assert '--glob=!**/.tmp_cli_manual/**' in action.command
        assert '--exclude-dir=.mypy_cache' in action.command
        assert '--exclude-dir=.tmp_cli_manual' in action.command
        assert '--binary-files=without-match' in action.command

    def test_file_discovery_prunes_generated_dirs(self, monkeypatch) -> None:
        monkeypatch.setattr(search_code_mod, 'uses_powershell_terminal', lambda: False)
        action = build_search_code_action(file_pattern='*.py')

        assert '-name .mypy_cache' in action.command
        assert '-name .tmp_cli_manual' in action.command
        assert "-prune -o -type f -name '*.py' -print" in action.command


class TestBuildSearchCodeActionPowerShell:
    """Verify PowerShell-safe command generation when bash is unavailable."""

    def test_search_mode_uses_powershell(self, monkeypatch) -> None:
        monkeypatch.setattr(search_code_mod, 'uses_powershell_terminal', lambda: True)
        action = build_search_code_action(pattern='my_pattern', path='.')
        cmd = action.command
        assert 'Get-Command rg' in cmd or 'Select-String' in cmd
        assert 'if command -v' not in cmd
        assert 'grep ' not in cmd
        # Excluded dirs should still be present in some form
        assert '.mypy_cache' in cmd

    def test_file_discovery_uses_get_childitem(self, monkeypatch) -> None:
        monkeypatch.setattr(search_code_mod, 'uses_powershell_terminal', lambda: True)
        action = build_search_code_action(file_pattern='*.py', path='.')
        cmd = action.command
        assert 'Get-ChildItem' in cmd
        assert 'find ' not in cmd

    def test_file_discovery_without_pattern_uses_get_childitem(self, monkeypatch) -> None:
        monkeypatch.setattr(search_code_mod, 'uses_powershell_terminal', lambda: True)
        action = build_search_code_action(path='src')
        cmd = action.command
        assert 'Get-ChildItem' in cmd
