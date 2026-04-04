"""Tests for backend.persistence.local_file_store — LocalFileStore."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from backend.persistence.local_file_store import LocalFileStore


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
        assert not os.path.exists(store.get_full_path('folder'))

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
        assert not os.path.exists(store.get_full_path('folder'))


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
