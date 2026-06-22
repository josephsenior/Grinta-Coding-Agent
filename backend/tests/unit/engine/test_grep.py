from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from backend.engine.tools.grep import build_grep_action, execute_grep
from backend.ledger.observation import ErrorObservation
from backend.ledger.observation.search import GrepObservation


@pytest.fixture(autouse=True)
def _workspace_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        'backend.core.workspace_resolution.require_effective_workspace_root',
        lambda: tmp_path,
    )


class TestExecuteGrep:
    def test_text_search_with_python_fallback(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(shutil, 'which', lambda x: None)

        test_file = tmp_path / 'test.py'
        test_file.write_text(
            "def my_func():\n    print('hello world')\n", encoding='utf-8'
        )

        ignored_dir = tmp_path / '.mypy_cache'
        ignored_dir.mkdir()
        ignored_file = ignored_dir / 'hidden.py'
        ignored_file.write_text("print('hello world')\n", encoding='utf-8')

        action = build_grep_action(
            pattern='hello world',
            path=str(tmp_path),
            output_mode='files_with_matches',
        )
        obs = execute_grep(action)

        assert isinstance(obs, GrepObservation)
        assert 'test.py' in obs.content
        assert '.mypy_cache' not in obs.content

    def test_content_mode_returns_matching_lines(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(shutil, 'which', lambda x: None)

        test_file = tmp_path / 'test.py'
        test_file.write_text(
            "def my_func():\n    print('hello world')\n", encoding='utf-8'
        )

        action = build_grep_action(
            pattern='hello world',
            path=str(tmp_path),
            output_mode='content',
        )
        obs = execute_grep(action)

        assert 'hello world' in obs.content
        assert 'test.py' in obs.content

    def test_count_mode_returns_per_file_counts(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(shutil, 'which', lambda x: None)

        test_file = tmp_path / 'test.py'
        test_file.write_text('todo\nTODO\n', encoding='utf-8')

        action = build_grep_action(
            pattern='todo',
            path=str(tmp_path),
            output_mode='count',
            case_sensitive=False,
        )
        obs = execute_grep(action)

        assert 'test.py:' in obs.content

    def test_head_limit_paginates_output(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(shutil, 'which', lambda x: None)

        for index in range(5):
            (tmp_path / f'file{index}.py').write_text('match\n', encoding='utf-8')

        action = build_grep_action(
            pattern='match',
            path=str(tmp_path),
            output_mode='files_with_matches',
            head_limit=2,
        )
        obs = execute_grep(action)

        # The Python fallback iterates files in filesystem order, which varies
        # by platform.  Assert only that exactly head_limit (2) files appear.
        matched_files = [
            f'file{i}.py' for i in range(5) if f'file{i}.py' in obs.content
        ]
        assert len(matched_files) == 2

    def test_invalid_regex_returns_friendly_error(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(shutil, 'which', lambda x: None)

        action = build_grep_action(pattern='(unclosed', path=str(tmp_path))
        obs = execute_grep(action)

        assert isinstance(obs, ErrorObservation)
        assert 'Invalid regex' in obs.content
        assert obs.tool_result['error_code'] == 'INVALID_PATTERN'

    def test_missing_path_returns_error(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(shutil, 'which', lambda x: None)

        action = build_grep_action(pattern='hello', path=str(tmp_path / 'nope'))
        obs = execute_grep(action)

        assert isinstance(obs, ErrorObservation)
        assert 'Path does not exist' in obs.content
        assert obs.tool_result['error_code'] == 'PATH_NOT_FOUND'

    def test_empty_pattern_rejected(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(shutil, 'which', lambda x: None)

        action = build_grep_action(pattern='', path=str(tmp_path))
        obs = execute_grep(action)

        assert isinstance(obs, ErrorObservation)
        assert 'non-empty' in obs.content
        assert obs.tool_result['error_code'] == 'VALIDATION_ERROR'

    def test_outside_workspace_path_rejected(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(shutil, 'which', lambda x: None)
        outside = tmp_path.parent / 'outside_workspace_grep'
        outside.mkdir(exist_ok=True)
        action = build_grep_action(pattern='hello', path=str(outside))
        obs = execute_grep(action)
        assert isinstance(obs, ErrorObservation)
        assert 'outside workspace boundary' in obs.content.lower()
