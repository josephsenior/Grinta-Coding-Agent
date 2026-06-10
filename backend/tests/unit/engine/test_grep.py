from __future__ import annotations

import shutil

from backend.engine.tools.grep import build_grep_action


class TestBuildGrepAction:
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

        assert 'test.py' in action.thought
        assert '.mypy_cache' not in action.thought

    def test_content_mode_returns_matching_lines(
        self, tmp_path, monkeypatch
    ) -> None:
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

        assert 'hello world' in action.thought
        assert 'test.py' in action.thought

    def test_count_mode_returns_per_file_counts(
        self, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.setattr(shutil, 'which', lambda x: None)

        test_file = tmp_path / 'test.py'
        test_file.write_text('todo\nTODO\n', encoding='utf-8')

        action = build_grep_action(
            pattern='todo',
            path=str(tmp_path),
            output_mode='count',
            case_sensitive=False,
        )

        assert 'test.py:' in action.thought

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

        assert 'file0.py' in action.thought
        assert 'file1.py' in action.thought
        assert 'file4.py' not in action.thought

    def test_invalid_regex_returns_friendly_error(
        self, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.setattr(shutil, 'which', lambda x: None)

        action = build_grep_action(pattern='(unclosed', path=str(tmp_path))

        assert 'Invalid regex' in action.thought
        assert 'glob' in action.thought

    def test_missing_path_returns_error(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(shutil, 'which', lambda x: None)

        action = build_grep_action(pattern='hello', path=str(tmp_path / 'nope'))

        assert 'Path does not exist' in action.thought

    def test_empty_pattern_rejected(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(shutil, 'which', lambda x: None)

        action = build_grep_action(pattern='', path=str(tmp_path))

        assert 'non-empty' in action.thought
        assert 'glob' in action.thought
