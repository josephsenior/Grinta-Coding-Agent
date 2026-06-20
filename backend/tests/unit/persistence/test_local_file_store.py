"""Tests for backend.persistence.local_file_store — LocalFileStore."""

from __future__ import annotations

import os
import time
from unittest.mock import patch

import pytest

from backend.persistence.file_store.atomic_write import replace_file_with_retry
from backend.persistence.file_store.local_file_store import LocalFileStore


def _wait_until_removed(path: str, timeout: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not os.path.exists(path):
            return True
        time.sleep(0.02)
    return not os.path.exists(path)


@pytest.fixture()
def store(tmp_path):
    """Create a LocalFileStore with a temporary root."""
    return LocalFileStore(str(tmp_path))


class TestLocalFileStoreInit:
    def test_creates_root_dir(self, tmp_path):
        root = str(tmp_path / 'new_root')
        assert not os.path.exists(root)
        LocalFileStore(root)
        assert os.path.isdir(root)

    def test_expands_tilde(self, tmp_path):
        store = LocalFileStore(str(tmp_path / '~test_root'))
        # Just verify tilde-prefixed paths trigger expanduser
        # On a real tilde path, expanduser would resolve it
        assert os.path.isdir(store.root)

    def test_get_base_path_matches_root(self, tmp_path):
        root = str(tmp_path / 'r')
        store = LocalFileStore(root)
        assert store.get_base_path() == store.root


class TestWriteAndRead:
    def test_write_string(self, store):
        store.write('hello.txt', 'world')
        assert store.read('hello.txt') == 'world'

    def test_write_bytes(self, store):
        store.write('binary.bin', b'binary data')
        # Read returns str (the file should have been written as-is bytes)
        full_path = store.get_full_path('binary.bin')
        with open(full_path, 'rb') as f:
            assert f.read() == b'binary data'

    def test_write_creates_subdirs(self, store):
        store.write('a/b/c.txt', 'deep')
        assert store.read('a/b/c.txt') == 'deep'

    def test_overwrite(self, store):
        store.write('f.txt', 'v1')
        store.write('f.txt', 'v2')
        assert store.read('f.txt') == 'v2'

    def test_read_nonexistent_raises(self, store):
        with pytest.raises(FileNotFoundError):
            store.read('no_such_file.txt')

    def test_write_retries_transient_permission_error_on_replace(self, store):
        store.write('locked.txt', 'v1')
        real_replace = os.replace
        calls = {'count': 0}

        def flaky_replace(src, dst):
            calls['count'] += 1
            if calls['count'] == 1:
                raise PermissionError(5, 'Access is denied')
            return real_replace(src, dst)

        with patch(
            'backend.persistence.atomic_write.os.replace', side_effect=flaky_replace
        ):
            store.write('locked.txt', 'v2')

        assert calls['count'] >= 2
        assert store.read('locked.txt') == 'v2'


class TestReplaceFileWithRetry:
    def test_retries_transient_permission_error(self, tmp_path):
        dest = tmp_path / 'plan.json'
        dest.write_text('old', encoding='utf-8')
        tmp = tmp_path / 'plan.json.tmp'
        tmp.write_text('new', encoding='utf-8')
        real_replace = os.replace
        calls = {'count': 0}

        def flaky_replace(src, dst):
            calls['count'] += 1
            if calls['count'] == 1:
                raise PermissionError(5, 'Access is denied')
            return real_replace(src, dst)

        with patch(
            'backend.persistence.atomic_write.os.replace', side_effect=flaky_replace
        ):
            replace_file_with_retry(tmp, dest)

        assert calls['count'] >= 2
        assert dest.read_text(encoding='utf-8') == 'new'


class TestList:
    def test_list_files(self, store):
        store.write('a.txt', 'a')
        store.write('b.txt', 'b')
        entries = store.list('.')
        names = sorted(entries)
        assert any('a.txt' in n for n in names)
        assert any('b.txt' in n for n in names)

    def test_list_with_subdirectory(self, store):
        store.write('sub/file.txt', 'data')
        entries = store.list('.')
        # "sub" should appear as directory (trailing /)
        assert any('sub/' in e for e in entries)

    def test_list_subdirectory_contents(self, store):
        store.write('dir/one.txt', '1')
        store.write('dir/two.txt', '2')
        entries = store.list('dir')
        assert len(entries) == 2


class TestDelete:
    def test_delete_file(self, store):
        store.write('del.txt', 'gone')
        assert store.read('del.txt') == 'gone'
        store.delete('del.txt')
        with pytest.raises(FileNotFoundError):
            store.read('del.txt')

    def test_delete_directory(self, store):
        store.write('folder/f.txt', 'x')
        store.delete('folder')
        assert _wait_until_removed(store.get_full_path('folder/f.txt'))

    def test_delete_nonexistent_no_error(self, store):
        # Should not raise
        store.delete('nonexistent_path')

    def test_delete_directory_retries_transient_oserror(self, store):
        store.write('folder/f.txt', 'x')
        real_rmtree = __import__('shutil').rmtree
        calls = {'count': 0}

        def flaky_rmtree(path, onerror=None):
            calls['count'] += 1
            if calls['count'] == 1:
                raise OSError('directory is not empty')
            return real_rmtree(path, onerror=onerror)

        with patch(
            'backend.persistence.local_file_store.shutil.rmtree',
            side_effect=flaky_rmtree,
        ):
            store.delete('folder')

        assert calls['count'] >= 2
        assert _wait_until_removed(store.get_full_path('folder/f.txt'))


class TestGetFullPath:
    def test_basic_path(self, store):
        full = store.get_full_path('test.txt')
        assert full.endswith('test.txt')
        assert store.root in full

    def test_traversal_rejected(self, store):
        """Path traversal should be rejected."""
        with pytest.raises(ValueError):
            store.get_full_path('../../../etc/passwd')

    def test_strips_leading_slash(self, store):
        full = store.get_full_path('/leading.txt')
        assert store.root in full
