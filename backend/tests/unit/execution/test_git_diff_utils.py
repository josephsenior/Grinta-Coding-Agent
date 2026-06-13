"""Tests for backend.execution.utils.git_diff."""

from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.execution.utils import git_diff as gd


def test_get_closest_git_repo_returns_repo_root(tmp_path: Path) -> None:
    repo = tmp_path / 'repo'
    git_dir = repo / '.git'
    git_dir.mkdir(parents=True)
    nested = repo / 'src' / 'pkg'
    nested.mkdir(parents=True)
    file_path = nested / 'x.py'
    file_path.write_text('a', encoding='utf-8')
    assert gd.get_closest_git_repo(file_path.resolve()) == repo.resolve()


def test_get_closest_git_repo_returns_none_without_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    isolated = tmp_path / 'no_git' / 'f.txt'
    isolated.parent.mkdir(parents=True)
    isolated.write_text('x', encoding='utf-8')

    orig_is_dir = Path.is_dir

    def mock_is_dir(self: Path) -> bool:
        if self.name == '.git':
            try:
                self.relative_to(tmp_path)
            except ValueError:
                return False
        return orig_is_dir(self)

    monkeypatch.setattr(Path, 'is_dir', mock_is_dir)
    assert gd.get_closest_git_repo(isolated.resolve()) is None


def test_get_git_diff_file_too_large_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    p = Path('big.txt')
    p.write_bytes(b'x' * (gd.MAX_FILE_SIZE_FOR_GIT_DIFF + 1))
    with pytest.raises(ValueError, match='file_to_large'):
        gd.get_git_diff('big.txt')


def test_get_git_diff_success_reads_modified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / 'r'
    (repo / '.git').mkdir(parents=True)
    rel = Path('f.txt')
    full = repo / rel
    full.write_text('modified\n', encoding='utf-8')
    monkeypatch.chdir(repo)
    with (
        patch.object(gd, 'get_closest_git_repo', return_value=repo.resolve()),
        patch.object(gd, 'get_valid_git_ref', return_value='HEAD'),
        patch.object(gd, 'run_git_args', return_value='original\n'),
    ):
        out = gd.get_git_diff(str(rel))
    assert out['modified'] == 'modified'
    assert out['original'].strip() == 'original'


def test_get_git_diff_uses_posix_git_object_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / 'r'
    (repo / '.git').mkdir(parents=True)
    rel = Path('src') / 'pkg' / 'f.txt'
    full = repo / rel
    full.parent.mkdir(parents=True)
    full.write_text('modified\n', encoding='utf-8')
    monkeypatch.chdir(repo)
    with (
        patch.object(gd, 'get_closest_git_repo', return_value=repo.resolve()),
        patch.object(gd, 'get_valid_git_ref', return_value='HEAD'),
        patch.object(gd, 'run_git_args', return_value='original\n') as run_git_args,
    ):
        gd.get_git_diff(str(rel))

    assert run_git_args.call_args.args[0] == ['git', 'show', 'HEAD:src/pkg/f.txt']


def test_fallback_print_writes_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    buf = io.StringIO()
    monkeypatch.setattr('sys.stdout', buf)
    gd._fallback_print({'ok': True})
    assert json.loads(buf.getvalue()) == {'ok': True}
