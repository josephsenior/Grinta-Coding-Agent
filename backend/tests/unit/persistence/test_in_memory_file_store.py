"""Tests for backend.persistence.in_memory_file_store — InMemoryFileStore."""

import pytest

from backend.persistence.file_store.in_memory_file_store import InMemoryFileStore


class TestInMemoryFileStoreInit:
    def test_default_empty(self):
        store = InMemoryFileStore()
        assert store.files == {}

    def test_prepopulated(self):
        store = InMemoryFileStore({'a.txt': 'hello'})
        assert store.files == {'a.txt': 'hello'}


class TestWrite:
    def test_write_string(self):
        store = InMemoryFileStore()
        store.write('file.txt', 'content')
        assert store.files['file.txt'] == 'content'

    def test_write_bytes(self):
        store = InMemoryFileStore()
        store.write('file.bin', b'binary content')
        assert store.files['file.bin'] == 'binary content'

    def test_overwrite(self):
        store = InMemoryFileStore({'f.txt': 'old'})
        store.write('f.txt', 'new')
        assert store.files['f.txt'] == 'new'


class TestRead:
    def test_read_existing(self):
        store = InMemoryFileStore({'hello.txt': 'world'})
        assert store.read('hello.txt') == 'world'

    def test_read_not_found(self):
        store = InMemoryFileStore()
        with pytest.raises(FileNotFoundError):
            store.read('nonexistent.txt')


class TestList:
    def test_list_root_files(self):
        store = InMemoryFileStore(
            {
                'a.txt': 'a',
                'b.txt': 'b',
            }
        )
        result = store.list('')
        assert sorted(result) == ['a.txt', 'b.txt']

    def test_list_subdirectory_files(self):
        store = InMemoryFileStore(
            {
                'dir/a.txt': 'a',
                'dir/b.txt': 'b',
                'other.txt': 'o',
            }
        )
        result = store.list('dir/')
        assert sorted(result) == ['dir/a.txt', 'dir/b.txt']

    def test_list_shows_subdirs(self):
        store = InMemoryFileStore(
            {
                'dir/sub/a.txt': 'a',
                'dir/sub/b.txt': 'b',
                'dir/c.txt': 'c',
            }
        )
        result = store.list('dir/')
        assert 'dir/c.txt' in result
        assert 'dir/sub/' in result

    def test_list_empty_dir(self):
        store = InMemoryFileStore({'other/file.txt': 'x'})
        result = store.list('empty/')
        assert result == []

    def test_list_deduplicates_subdirs(self):
        store = InMemoryFileStore(
            {
                'dir/sub/a.txt': 'a',
                'dir/sub/b.txt': 'b',
            }
        )
        result = store.list('dir/')
        # "dir/sub/" should appear only once
        assert result.count('dir/sub/') == 1


class TestDelete:
    def test_delete_single_file(self):
        store = InMemoryFileStore({'a.txt': 'a', 'b.txt': 'b'})
        store.delete('a.txt')
        assert 'a.txt' not in store.files
        assert 'b.txt' in store.files

    def test_delete_by_prefix(self):
        store = InMemoryFileStore(
            {
                'dir/a.txt': 'a',
                'dir/b.txt': 'b',
                'other.txt': 'o',
            }
        )
        store.delete('dir/')
        assert store.files == {'other.txt': 'o'}

    def test_delete_nonexistent_no_error(self):
        store = InMemoryFileStore()
        store.delete('missing.txt')  # Should not raise


class TestIntegration:
    def test_write_read_delete_cycle(self):
        store = InMemoryFileStore()
        store.write('test/file.txt', 'hello world')
        assert store.read('test/file.txt') == 'hello world'
        assert store.list('test/') == ['test/file.txt']
        store.delete('test/file.txt')
        with pytest.raises(FileNotFoundError):
            store.read('test/file.txt')


class TestInMemoryFileStoreCoverageGaps:
    def test_list_without_trailing_slash(self):
        store = InMemoryFileStore({'dir/a.txt': 'hello', 'dir': 'world'})
        # 1. 'dir/a.txt' with path='dir' -> suffix='/a.txt' -> parts=['', 'a.txt'] -> pops first empty -> ['a.txt']
        # 2. 'dir' with path='dir' -> suffix='' -> parts=[''] -> pops -> [] -> triggers 'if not parts: continue'
        result = store.list('dir')
        assert 'dir/a.txt' in result

    def test_delete_exception_caught(self):
        from unittest.mock import MagicMock

        store = InMemoryFileStore()
        # Mock files dictionary to raise exception on iteration
        store.files = MagicMock()
        store.files.__iter__.side_effect = RuntimeError('mocked delete error')

        # Should not raise exception
        store.delete('path')
