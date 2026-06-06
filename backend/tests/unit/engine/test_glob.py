from __future__ import annotations

import shutil

from backend.engine.tools.glob import build_glob_action


class TestBuildGlobAction:
    def test_file_discovery_with_python_fallback(
        self, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.setattr(shutil, 'which', lambda x: None)

        (tmp_path / 'test1.py').touch()
        (tmp_path / 'test2.js').touch()

        action = build_glob_action(pattern='*.py', path=str(tmp_path))

        assert 'test1.py' in action.thought
        assert 'test2.js' not in action.thought

    def test_nested_glob_with_python_fallback(
        self, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.setattr(shutil, 'which', lambda x: None)

        src_dir = tmp_path / 'src' / 'deep'
        src_dir.mkdir(parents=True)
        (src_dir / 'nested1.py').touch()
        (src_dir / 'ignore.txt').touch()

        action = build_glob_action(
            pattern='src/**/*.py', path=str(tmp_path)
        )
        assert 'nested1.py' in action.thought
        assert 'ignore.txt' not in action.thought

        action2 = build_glob_action(pattern='**/*.py', path=str(tmp_path))
        assert 'nested1.py' in action2.thought
        assert 'ignore.txt' not in action2.thought

    def test_hidden_file_pattern_globbing(
        self, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.setattr(shutil, 'which', lambda x: None)

        (tmp_path / '.env').write_text('SECRET=value\n', encoding='utf-8')
        (tmp_path / 'README.md').write_text('# hello\n', encoding='utf-8')

        action = build_glob_action(pattern='.env', path=str(tmp_path))

        assert '.env' in action.thought

    def test_missing_path_returns_error(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(shutil, 'which', lambda x: None)

        action = build_glob_action(pattern='*.py', path=str(tmp_path / 'nope'))

        assert 'Path does not exist' in action.thought

    def test_empty_pattern_rejected(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(shutil, 'which', lambda x: None)

        action = build_glob_action(pattern='', path=str(tmp_path))

        assert 'non-empty' in action.thought
        assert 'grep' in action.thought
