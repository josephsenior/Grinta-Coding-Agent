from __future__ import annotations

import shutil

from backend.engine.tools.grep import build_grep_action, execute_grep
from backend.ledger.observation.search import GrepObservation


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

        assert 'file0.py' in obs.content
        assert 'file1.py' in obs.content
        assert 'file4.py' not in obs.content

    def test_invalid_regex_returns_friendly_error(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(shutil, 'which', lambda x: None)

        action = build_grep_action(pattern='(unclosed', path=str(tmp_path))
        obs = execute_grep(action)

        assert 'Invalid regex' in obs.content
        assert obs.error
        assert 'glob' in obs.content

    def test_missing_path_returns_error(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(shutil, 'which', lambda x: None)

        action = build_grep_action(pattern='hello', path=str(tmp_path / 'nope'))
        obs = execute_grep(action)

        assert 'Path does not exist' in obs.content
        assert obs.error

    def test_empty_pattern_rejected(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(shutil, 'which', lambda x: None)

        action = build_grep_action(pattern='', path=str(tmp_path))
        obs = execute_grep(action)

        assert 'non-empty' in obs.content
        assert obs.error
        assert 'glob' in obs.content
