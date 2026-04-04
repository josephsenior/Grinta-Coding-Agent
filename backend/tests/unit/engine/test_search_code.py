from __future__ import annotations

from backend.engine.tools.search_code import build_search_code_action


class TestBuildSearchCodeAction:
    def test_search_mode_excludes_generated_dirs_for_rg_and_grep(self) -> None:
        action = build_search_code_action(pattern='show_grinta_splash')

        assert '--glob=!**/.mypy_cache/**' in action.command
        assert '--glob=!**/.tmp_cli_manual/**' in action.command
        assert '--exclude-dir=.mypy_cache' in action.command
        assert '--exclude-dir=.tmp_cli_manual' in action.command
        assert '--binary-files=without-match' in action.command

    def test_file_discovery_prunes_generated_dirs(self) -> None:
        action = build_search_code_action(file_pattern='*.py')

        assert '-name .mypy_cache' in action.command
        assert '-name .tmp_cli_manual' in action.command
        assert "-prune -o -type f -name '*.py' -print" in action.command
