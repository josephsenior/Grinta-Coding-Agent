from __future__ import annotations

import shutil

from backend.engine.tools.glob import build_glob_action, execute_glob
from backend.ledger.observation.search import GlobObservation


class TestExecuteGlob:
    def test_file_discovery_with_python_fallback(
        self, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.setattr(shutil, 'which', lambda x: None)

        (tmp_path / 'test1.py').touch()
        (tmp_path / 'test2.js').touch()

        action = build_glob_action(pattern='*.py', path=str(tmp_path))
        obs = execute_glob(action)

        assert isinstance(obs, GlobObservation)
        assert 'test1.py' in obs.content
        assert 'test2.js' not in obs.content

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
        obs = execute_glob(action)
        assert 'nested1.py' in obs.content
        assert 'ignore.txt' not in obs.content

        action2 = build_glob_action(pattern='**/*.py', path=str(tmp_path))
        obs2 = execute_glob(action2)
        assert 'nested1.py' in obs2.content
        assert 'ignore.txt' not in obs2.content

    def test_hidden_file_pattern_globbing(
        self, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.setattr(shutil, 'which', lambda x: None)

        (tmp_path / '.env').write_text('SECRET=value\n', encoding='utf-8')
        (tmp_path / 'README.md').write_text('# hello\n', encoding='utf-8')

        action = build_glob_action(pattern='.env', path=str(tmp_path))
        obs = execute_glob(action)

        assert '.env' in obs.content

    def test_missing_path_returns_error(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(shutil, 'which', lambda x: None)

        action = build_glob_action(pattern='*.py', path=str(tmp_path / 'nope'))
        obs = execute_glob(action)

        assert 'Path does not exist' in obs.content
        assert obs.error

    def test_empty_pattern_rejected(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(shutil, 'which', lambda x: None)

        action = build_glob_action(pattern='', path=str(tmp_path))
        obs = execute_glob(action)

        assert 'non-empty' in obs.content
        assert obs.error
        assert 'grep' in obs.content
