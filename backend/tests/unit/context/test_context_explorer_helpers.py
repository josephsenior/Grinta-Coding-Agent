"""Unit tests for context explorer helper functions."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from backend.context import context_explorer as ce


def test_normalize_rel_path_and_candidate_filter() -> None:
    assert ce._normalize_rel_path('.\\src\\main.py') == 'src/main.py'
    assert ce._is_candidate_path('src/main.py') is True
    assert ce._is_candidate_path('node_modules/pkg/index.js') is False
    assert ce._is_candidate_path('README.txt') is False


def test_query_terms_and_mentioned_paths() -> None:
    task = 'Fix backend/auth.py token refresh in AuthService'
    terms = ce._query_terms(task)
    assert 'auth' in terms or 'token' in terms
    mentions = ce._mentioned_paths(task)
    assert 'backend/auth.py' in mentions


def test_identifier_and_path_tokens() -> None:
    tokens = ce._identifier_tokens('refreshToken_handler-v2')
    assert 'refresh' in tokens or 'Token' in tokens or 'handler' in tokens
    assert 'auth' in ce._path_tokens('backend/auth_service.py')


def test_candidate_draft_accumulates_score() -> None:
    draft = ce._CandidateDraft(path='a.py')
    draft.add(10, 'mentioned in task')
    draft.add(5, 'dirty file')
    assert draft.score == 15
    assert draft.reasons == {'mentioned in task', 'dirty file'}


def test_collect_python_symbols(tmp_path: Path) -> None:
    source = tmp_path / 'service.py'
    source.write_text(
        'class AuthService:\n    def refresh_token(self):\n        return 1\n',
        encoding='utf-8',
    )
    symbols = ce._collect_python_symbols(source, {'token', 'refresh'})
    assert 'refresh_token' in symbols or 'AuthService' in symbols


def test_git_status_lines_uses_subprocess(tmp_path: Path, monkeypatch) -> None:
    class Result:
        returncode = 0
        stdout = ' M backend/auth.py\n'

    monkeypatch.setattr(ce, '_run', lambda *_a, **_k: Result())
    lines = ce.git_status_lines(tmp_path)
    assert lines == [' M backend/auth.py']


def test_repo_files_prefers_git_listing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(ce, '_git_files', lambda _root: ['src/a.py'])
    monkeypatch.setattr(ce, '_walk_files', lambda _root: ['walk.py'])
    assert ce._repo_files(tmp_path) == ['src/a.py']


def test_walk_files_collects_source_files(tmp_path: Path) -> None:
    (tmp_path / 'src').mkdir()
    (tmp_path / 'src' / 'main.py').write_text('x = 1\n', encoding='utf-8')
    (tmp_path / 'node_modules' / 'pkg').mkdir(parents=True)
    (tmp_path / 'node_modules' / 'pkg' / 'index.js').write_text('', encoding='utf-8')
    files = ce._walk_files(tmp_path)
    assert 'src/main.py' in files
    assert not any('node_modules' in path for path in files)


def test_dirty_paths_parses_git_status(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        ce,
        'git_status_lines',
        lambda _root, limit=100: [' M backend/auth.py', '?? src/new.py'],
    )
    dirty = ce._dirty_paths(tmp_path)
    assert 'backend/auth.py' in dirty
    assert 'src/new.py' in dirty


def test_content_hits_aggregates_rg_matches(tmp_path: Path, monkeypatch) -> None:
    class Result:
        returncode = 0
        stdout = 'backend/auth.py\nbackend/token.py\n'

    monkeypatch.setattr(ce, '_run', lambda *_a, **_k: Result())
    hits = ce._content_hits(tmp_path, ['token', 'ab'])
    assert 'backend/auth.py' in hits
    assert 'token' in hits['backend/auth.py']


def test_draft_for_reuses_normalized_path() -> None:
    drafts: dict[str, ce._CandidateDraft] = {}
    first = ce._draft_for(drafts, '.\\src\\main.py')
    second = ce._draft_for(drafts, 'src/main.py')
    assert first is second
    assert len(drafts) == 1


def test_git_files_returns_empty_on_failure(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(ce, '_run', lambda *_a, **_k: None)
    assert ce._git_files(tmp_path) == []


def test_run_returns_none_on_subprocess_error(tmp_path: Path, monkeypatch) -> None:
    def _boom(*_a, **_k):
        raise OSError('boom')

    monkeypatch.setattr(ce.subprocess, 'run', _boom)
    assert ce._run(['git', 'status'], tmp_path) is None


def test_git_status_lines_returns_empty_when_git_fails(tmp_path: Path, monkeypatch) -> None:
    class Result:
        returncode = 1
        stdout = ''

    monkeypatch.setattr(ce, '_run', lambda *_a, **_k: Result())
    assert ce.git_status_lines(tmp_path) == []


def test_content_hits_skips_short_terms_and_too_many_paths(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(ce, '_run', lambda *_a, **_k: None)
    assert ce._content_hits(tmp_path, ['ab', 'token']) == {}
    many_paths = '\n'.join(f'file{i}.py' for i in range(100))

    class Result:
        returncode = 0
        stdout = many_paths

    monkeypatch.setattr(ce, '_run', lambda *_a, **_k: Result())
    assert ce._content_hits(tmp_path, ['token']) == {}


def test_explore_context_ranks_mentioned_and_dirty(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / 'backend' / 'auth.py'
    source.parent.mkdir(parents=True)
    source.write_text('def refresh_token():\n    pass\n', encoding='utf-8')
    monkeypatch.setattr(ce, '_git_files', lambda _root: ['backend/auth.py'])
    monkeypatch.setattr(ce, '_dirty_paths', lambda _root: {'backend/auth.py'})
    monkeypatch.setattr(ce, '_content_hits', lambda *_a, **_k: {})
    result = ce.explore_context('fix backend/auth.py refresh token', tmp_path)
    assert result.candidates
    assert result.candidates[0].path == 'backend/auth.py'
    assert result.query_terms
