"""Unit tests for backend.execution.rollback.shadow_repo.ShadowRepo."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / 'workspace'
    ws.mkdir()
    (ws / 'main.py').write_text("print('hello')", encoding='utf-8')
    (ws / 'lib').mkdir()
    (ws / 'lib' / 'utils.py').write_text('def util(): pass', encoding='utf-8')
    return ws


def _make_shadow_repo(workspace: Path, shadow_dir: Path):
    """Construct a ShadowRepo, skipping if pygit2 is unavailable."""
    pytest.importorskip('pygit2')
    from backend.execution.rollback.shadow_repo import ShadowRepo

    return ShadowRepo(workspace_root=workspace, shadow_dir=shadow_dir)


# ---------------------------------------------------------------------------
# ShadowRepo basic init
# ---------------------------------------------------------------------------


class TestShadowRepoInit:
    def test_init_creates_shadow_dir(self, tmp_path):
        ws = _make_workspace(tmp_path)
        shadow_dir = tmp_path / 'shadow'
        repo = _make_shadow_repo(ws, shadow_dir)
        assert shadow_dir.exists()
        assert repo is not None

    def test_default_shadow_dir_inside_grinta(self, tmp_path):
        pytest.importorskip('pygit2')
        from backend.execution.rollback.shadow_repo import ShadowRepo

        ws = _make_workspace(tmp_path)
        repo = ShadowRepo(workspace_root=ws)
        expected = ws / '.grinta' / 'shadow_repo'
        assert repo._shadow_dir == expected

    def test_reinit_reopens_existing(self, tmp_path):
        ws = _make_workspace(tmp_path)
        shadow_dir = tmp_path / 'shadow'
        repo1 = _make_shadow_repo(ws, shadow_dir)
        sha1 = repo1.snapshot(label='first')
        # Reopen -- should not crash and should still resolve the old commit.
        pytest.importorskip('pygit2')
        from backend.execution.rollback.shadow_repo import ShadowRepo

        repo2 = ShadowRepo(workspace_root=ws, shadow_dir=shadow_dir)
        inner = repo2._repo.get(sha1)
        assert inner is not None


# ---------------------------------------------------------------------------
# snapshot()
# ---------------------------------------------------------------------------


class TestSnapshot:
    def test_snapshot_returns_40_char_sha(self, tmp_path):
        ws = _make_workspace(tmp_path)
        repo = _make_shadow_repo(ws, tmp_path / 'shadow')
        sha = repo.snapshot(label='test')
        assert isinstance(sha, str)
        assert len(sha) == 40

    def test_snapshot_captures_all_files(self, tmp_path):
        ws = _make_workspace(tmp_path)
        shadow_dir = tmp_path / 'shadow'
        repo = _make_shadow_repo(ws, shadow_dir)
        sha = repo.snapshot()
        pygit2 = pytest.importorskip('pygit2')
        commit = repo._repo.get(sha)
        tree = commit.peel(pygit2.Tree)
        blobs: list[str] = []

        def _walk(t, prefix):
            for entry in t:
                rel = f'{prefix}{entry.name}' if prefix else entry.name
                if entry.type_str == 'blob':
                    blobs.append(rel)
                elif entry.type_str == 'tree':
                    _walk(repo._repo.get(entry.id), f'{rel}/')

        _walk(tree, '')
        assert 'main.py' in blobs
        assert 'lib/utils.py' in blobs

    def test_snapshot_excludes_git_dir(self, tmp_path):
        ws = _make_workspace(tmp_path)
        git_dir = ws / '.git'
        git_dir.mkdir()
        (git_dir / 'HEAD').write_text('ref: refs/heads/main')
        shadow_dir = tmp_path / 'shadow'
        repo = _make_shadow_repo(ws, shadow_dir)
        sha = repo.snapshot()
        pygit2 = pytest.importorskip('pygit2')
        commit = repo._repo.get(sha)
        tree = commit.peel(pygit2.Tree)
        names = [e.name for e in tree]
        assert '.git' not in names

    def test_snapshot_excludes_grinta_dir(self, tmp_path):
        ws = _make_workspace(tmp_path)
        grinta = ws / '.grinta'
        grinta.mkdir()
        (grinta / 'data.json').write_text('{}')
        shadow_dir = tmp_path / 'shadow'
        repo = _make_shadow_repo(ws, shadow_dir)
        sha = repo.snapshot()
        pygit2 = pytest.importorskip('pygit2')
        commit = repo._repo.get(sha)
        tree = commit.peel(pygit2.Tree)
        names = [e.name for e in tree]
        assert '.grinta' not in names

    def test_second_snapshot_same_tree_when_unchanged(self, tmp_path):
        ws = _make_workspace(tmp_path)
        shadow_dir = tmp_path / 'shadow'
        repo = _make_shadow_repo(ws, shadow_dir)

        sha1 = repo.snapshot(label='first')
        sha2 = repo.snapshot(label='second')

        pygit2 = pytest.importorskip('pygit2')
        tree1 = repo._repo.get(sha1).peel(pygit2.Tree)
        tree2 = repo._repo.get(sha2).peel(pygit2.Tree)
        # Tree OIDs are content-addressed; identical content == same OID.
        assert str(tree1.id) == str(tree2.id)

    def test_stat_cache_persisted_to_disk(self, tmp_path):
        ws = _make_workspace(tmp_path)
        shadow_dir = tmp_path / 'shadow'
        repo = _make_shadow_repo(ws, shadow_dir)
        repo.snapshot()
        assert (shadow_dir / 'stat_cache.json').exists()

    def test_stat_cache_loaded_on_reopen(self, tmp_path):
        ws = _make_workspace(tmp_path)
        shadow_dir = tmp_path / 'shadow'
        repo1 = _make_shadow_repo(ws, shadow_dir)
        repo1.snapshot()
        cache1 = dict(repo1._stat_cache)

        pytest.importorskip('pygit2')
        from backend.execution.rollback.shadow_repo import ShadowRepo

        repo2 = ShadowRepo(workspace_root=ws, shadow_dir=shadow_dir)
        assert repo2._stat_cache == cache1

    def test_snapshot_detects_changed_file(self, tmp_path):
        ws = _make_workspace(tmp_path)
        shadow_dir = tmp_path / 'shadow'
        repo = _make_shadow_repo(ws, shadow_dir)
        sha1 = repo.snapshot(label='before')

        (ws / 'main.py').write_text("print('changed')", encoding='utf-8')
        sha2 = repo.snapshot(label='after')

        assert sha1 != sha2

        pygit2 = pytest.importorskip('pygit2')
        tree1 = repo._repo.get(sha1).peel(pygit2.Tree)
        tree2 = repo._repo.get(sha2).peel(pygit2.Tree)
        assert str(tree1.id) != str(tree2.id)

    def test_snapshot_on_non_git_workspace(self, tmp_path):
        """Shadow repo must work even when workspace has no .git directory."""
        ws = tmp_path / 'plain_workspace'
        ws.mkdir()
        (ws / 'app.py').write_text('x = 1')
        shadow_dir = tmp_path / 'shadow'
        repo = _make_shadow_repo(ws, shadow_dir)
        sha = repo.snapshot()
        assert len(sha) == 40

    def test_snapshot_on_workspace_that_is_git_repo(self, tmp_path):
        """Shadow repo must not interfere with the workspace .git when present."""
        ws = _make_workspace(tmp_path)
        git_dir = ws / '.git'
        git_dir.mkdir()
        (git_dir / 'HEAD').write_text('ref: refs/heads/main')
        shadow_dir = tmp_path / 'shadow'
        repo = _make_shadow_repo(ws, shadow_dir)
        sha = repo.snapshot()
        assert len(sha) == 40
        # User .git must be untouched -- only shadow dir should have changes.
        assert (git_dir / 'HEAD').read_text() == 'ref: refs/heads/main'


# ---------------------------------------------------------------------------
# restore()
# ---------------------------------------------------------------------------


class TestRestore:
    def test_restore_returns_original_content(self, tmp_path):
        ws = _make_workspace(tmp_path)
        shadow_dir = tmp_path / 'shadow'
        repo = _make_shadow_repo(ws, shadow_dir)
        sha = repo.snapshot(label='baseline')

        # Modify workspace
        (ws / 'main.py').write_text("print('modified')", encoding='utf-8')

        repo.restore(sha)
        assert (ws / 'main.py').read_text(encoding='utf-8') == "print('hello')"

    def test_restore_recreates_deleted_file(self, tmp_path):
        ws = _make_workspace(tmp_path)
        shadow_dir = tmp_path / 'shadow'
        repo = _make_shadow_repo(ws, shadow_dir)
        sha = repo.snapshot()

        (ws / 'main.py').unlink()

        repo.restore(sha)
        assert (ws / 'main.py').read_text(encoding='utf-8') == "print('hello')"

    def test_restore_quarantines_extra_files(self, tmp_path):
        ws = _make_workspace(tmp_path)
        shadow_dir = tmp_path / 'shadow'
        repo = _make_shadow_repo(ws, shadow_dir)
        sha = repo.snapshot()

        (ws / 'extra.txt').write_text('unwanted', encoding='utf-8')

        qdir = repo.restore(sha)

        assert not (ws / 'extra.txt').exists()
        assert qdir is not None
        assert (qdir / 'extra.txt').read_text(encoding='utf-8') == 'unwanted'

    def test_restore_explicit_quarantine_dir(self, tmp_path):
        ws = _make_workspace(tmp_path)
        shadow_dir = tmp_path / 'shadow'
        qdir_explicit = tmp_path / 'my_quarantine'
        repo = _make_shadow_repo(ws, shadow_dir)
        sha = repo.snapshot()

        (ws / 'gone.txt').write_text('bye', encoding='utf-8')
        returned = repo.restore(sha, quarantine_dir=qdir_explicit)

        assert returned == qdir_explicit
        assert (qdir_explicit / 'gone.txt').exists()

    def test_restore_preserves_git_dir(self, tmp_path):
        ws = _make_workspace(tmp_path)
        git_dir = ws / '.git'
        git_dir.mkdir()
        (git_dir / 'HEAD').write_text('ref: refs/heads/main')
        shadow_dir = tmp_path / 'shadow'
        repo = _make_shadow_repo(ws, shadow_dir)
        sha = repo.snapshot()

        (ws / 'main.py').write_text('modified')
        repo.restore(sha)

        # .git must be untouched
        assert (git_dir / 'HEAD').read_text() == 'ref: refs/heads/main'

    def test_restore_preserves_grinta_dir(self, tmp_path):
        ws = _make_workspace(tmp_path)
        grinta = ws / '.grinta'
        grinta.mkdir()
        sentinel = grinta / 'sentinel.json'
        sentinel.write_text('{"keep": true}')
        shadow_dir = tmp_path / 'shadow'
        repo = _make_shadow_repo(ws, shadow_dir)
        sha = repo.snapshot()

        (ws / 'main.py').write_text('modified')
        repo.restore(sha)

        assert sentinel.read_text() == '{"keep": true}'

    def test_restore_unknown_sha_raises(self, tmp_path):
        from backend.execution.rollback.shadow_repo import ShadowRepoError

        ws = _make_workspace(tmp_path)
        shadow_dir = tmp_path / 'shadow'
        repo = _make_shadow_repo(ws, shadow_dir)
        repo.snapshot()

        with pytest.raises(ShadowRepoError):
            repo.restore('a' * 40)

    def test_restore_nested_dirs(self, tmp_path):
        ws = _make_workspace(tmp_path)
        shadow_dir = tmp_path / 'shadow'
        repo = _make_shadow_repo(ws, shadow_dir)
        sha = repo.snapshot()

        (ws / 'lib' / 'utils.py').unlink()

        repo.restore(sha)
        assert (ws / 'lib' / 'utils.py').read_text(
            encoding='utf-8'
        ) == 'def util(): pass'

    def test_restore_invalidates_stat_cache(self, tmp_path):
        ws = _make_workspace(tmp_path)
        shadow_dir = tmp_path / 'shadow'
        repo = _make_shadow_repo(ws, shadow_dir)
        sha = repo.snapshot()

        (ws / 'main.py').write_text('modified')
        repo.restore(sha)

        # Stat cache must be empty after restore (workspace was rewritten).
        assert repo._stat_cache == {}


# ---------------------------------------------------------------------------
# ShadowRepoError / import fallback
# ---------------------------------------------------------------------------


class TestShadowRepoError:
    def test_error_is_runtime_error(self):
        from backend.execution.rollback.shadow_repo import ShadowRepoError

        err = ShadowRepoError('test')
        assert isinstance(err, RuntimeError)

    def test_module_importable_without_pygit2(self, monkeypatch):
        """shadow_repo module must be importable even if pygit2 is absent.

        Only the ShadowRepo *constructor* (which does ``import pygit2``)
        should fail -- not the module import itself.
        """
        # Temporarily hide pygit2 from sys.modules.
        original = sys.modules.pop('pygit2', None)
        try:
            # Remove cached module so the import system re-evaluates it.
            sys.modules.pop('backend.execution.rollback.shadow_repo', None)
            import backend.execution.rollback.shadow_repo as mod  # noqa: F401

            assert hasattr(mod, 'ShadowRepo')
            assert hasattr(mod, 'ShadowRepoError')
        finally:
            if original is not None:
                sys.modules['pygit2'] = original


# ---------------------------------------------------------------------------
# Windows CRLF round-trip (conditional)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform != 'win32', reason='CRLF behaviour Windows-only')
class TestCrlfRoundTrip:
    def test_crlf_preserved(self, tmp_path):
        ws = tmp_path / 'ws'
        ws.mkdir()
        crlf_content = b'line1\r\nline2\r\n'
        (ws / 'windows.txt').write_bytes(crlf_content)
        shadow_dir = tmp_path / 'shadow'
        repo = _make_shadow_repo(ws, shadow_dir)
        sha = repo.snapshot()

        (ws / 'windows.txt').write_bytes(b'other\r\n')
        repo.restore(sha)

        assert (ws / 'windows.txt').read_bytes() == crlf_content
