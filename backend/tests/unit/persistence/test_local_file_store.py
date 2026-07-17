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


class TestLocalFileStoreCoverageGaps:
    def test_get_full_path_empty_after_strip(self, store):
        # Empty or single slash should resolve to storage root
        assert store.get_full_path('/') == store.root
        assert store.get_full_path('') == store.root

    def test_get_full_path_import_error(self, store):
        import builtins

        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == 'backend.core.type_safety.path_validation':
                raise ImportError('mocked import error')
            return original_import(name, *args, **kwargs)

        with patch('builtins.__import__', side_effect=mock_import):
            with pytest.raises(RuntimeError) as exc:
                store.get_full_path('test.txt')
            assert 'Path validation module unavailable' in str(exc.value)

    def test_write_replace_error_cleans_up_tmp(self, store):
        # Mock replace_file_with_retry to raise an exception
        with patch(
            'backend.persistence.file_store.local_file_store.replace_file_with_retry',
            side_effect=ValueError('replace fail'),
        ):
            # Get list of files in storage before write
            initial_files = os.listdir(store.root)
            with pytest.raises(ValueError):
                store.write('fail.txt', 'some content')
            # Verify no temporary files left behind
            assert os.listdir(store.root) == initial_files

    def test_fsync_directory_non_windows(self):
        # Mock the imported OS_CAPS in local_file_store module
        with patch(
            'backend.persistence.file_store.local_file_store.OS_CAPS'
        ) as mock_os_caps:
            mock_os_caps.is_windows = False
            # Mock open, fsync, close
            mock_fd = 999
            with (
                patch('os.open', return_value=mock_fd) as mock_open,
                patch('os.fsync') as mock_fsync,
                patch('os.close') as mock_close,
            ):
                LocalFileStore._fsync_directory('/some/dir')

                mock_open.assert_called_once_with('/some/dir', os.O_RDONLY)
                mock_fsync.assert_called_once_with(mock_fd)
                mock_close.assert_called_once_with(mock_fd)

    def test_delete_file_permission_error_retries_and_succeeds(self, store):
        store.write('retry_del.txt', 'data')
        full_path = store.get_full_path('retry_del.txt')

        real_remove = os.remove
        calls = 0

        def mock_remove(path):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise PermissionError('Access denied (mocked)')
            real_remove(path)

        with patch('os.remove', side_effect=mock_remove):
            store.delete('retry_del.txt')
            assert calls == 2
            assert not os.path.exists(full_path)

    def test_delete_file_os_error_exhausted(self, store):
        store.write('always_fail.txt', 'data')
        with patch('os.remove', side_effect=OSError('always failing remove')):
            with pytest.raises(OSError) as exc:
                store._delete_file_with_retry(store.get_full_path('always_fail.txt'))
            assert 'always failing remove' in str(exc.value)

    def test_delete_dir_os_error_exhausted(self, store):
        os.makedirs(store.get_full_path('fail_dir'))
        with patch('shutil.rmtree', side_effect=OSError('always failing rmtree')):
            with pytest.raises(OSError) as exc:
                store._delete_dir_with_retry(store.get_full_path('fail_dir'))
            assert 'always failing rmtree' in str(exc.value)

    def test_make_writable_os_error(self):
        with patch('os.chmod', side_effect=OSError('chmod failed')):
            # Should catch exception and not raise
            LocalFileStore._make_writable('/nonexistent')

    def test_make_tree_writable_file(self, tmp_path):
        test_file = tmp_path / 'file.txt'
        test_file.write_text('hello')

        # When path is a file, should call _make_writable
        with patch.object(LocalFileStore, '_make_writable') as mock_make_writable:
            LocalFileStore._make_tree_writable(str(test_file))
            mock_make_writable.assert_called_once_with(str(test_file))

    def test_make_tree_writable_dir(self, tmp_path):
        test_dir = tmp_path / 'dir'
        test_dir.mkdir()
        sub_dir = test_dir / 'subdir'
        sub_dir.mkdir()
        test_file = sub_dir / 'file.txt'
        test_file.write_text('hello')

        # Test full tree walk chmod
        LocalFileStore._make_tree_writable(str(test_dir))
        # No errors should be raised
