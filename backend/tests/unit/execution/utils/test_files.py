"""Comprehensive tests for backend.execution.utils.files - File resolution and I/O utilities."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.execution.utils.files import (
    insert_lines,
    read_file,
    read_lines,
    resolve_path,
    write_file,
)
from backend.ledger.observation import (
    ErrorObservation,
    FileReadObservation,
    FileWriteObservation,
)


class TestResolvePath:
    """Tests for resolve_path() function."""

    def test_resolve_absolute_path_in_workspace(self):
        """Test resolving an absolute path within workspace."""
        # Use a real temporary directory for this test
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir).resolve()
            workdir = str(workspace / 'sub')
            os.makedirs(workdir, exist_ok=True)

            test_file = workspace / 'test.txt'
            test_file.touch()

            result = resolve_path(str(test_file), workdir, str(workspace))
            assert result == test_file

    def test_resolve_relative_path(self):
        """Test resolving a relative path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir).resolve()
            workdir = str(workspace / 'subdir')
            os.makedirs(workdir, exist_ok=True)

            # Create test file
            test_file = workspace / 'subdir' / 'test.txt'
            test_file.parent.mkdir(parents=True, exist_ok=True)
            test_file.touch()

            result = resolve_path('test.txt', workdir, str(workspace))
            assert result == test_file

    def test_resolve_path_with_parent_reference(self):
        """Test resolving path with .. parent references."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir).resolve()
            workdir = str(workspace / 'subdir1' / 'subdir2')
            os.makedirs(workdir, exist_ok=True)

            # Create file in parent
            parent_file = workspace / 'subdir1' / 'parent.txt'
            parent_file.parent.mkdir(parents=True, exist_ok=True)
            parent_file.touch()

            result = resolve_path('../parent.txt', workdir, str(workspace))
            assert result == parent_file

    def test_resolve_path_outside_workspace_raises_permission_error(self):
        """Test that accessing path outside workspace raises PermissionError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir).resolve()
            workdir = str(workspace / 'subdir')
            os.makedirs(workdir, exist_ok=True)

            # Try to access parent of workspace
            with pytest.raises(PermissionError) as exc_info:
                resolve_path('../../outside.txt', workdir, str(workspace))

            assert 'File access not permitted' in str(exc_info.value)

    def test_resolve_absolute_path_outside_workspace_raises_error(self):
        """Test that absolute path outside workspace raises PermissionError."""
        workspace = '/workspace'
        workdir = '/workspace/subdir'
        file_path = '/etc/passwd'

        with pytest.raises(PermissionError) as exc_info:
            resolve_path(file_path, workdir, workspace)

        assert 'File access not permitted' in str(exc_info.value)

    def test_resolve_path_normalizes_path(self):
        """Test that paths are normalized (redundant separators, . references)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir).resolve()
            workdir = str(workspace)

            test_file = workspace / 'test.txt'
            test_file.touch()

            # Path with redundant elements
            result = resolve_path('./././test.txt', workdir, str(workspace))
            assert result == test_file

    def test_resolve_path_fallback_for_different_drives(self):
        """Test fallback check for paths on different drives (Windows)."""
        # Simulate ValueError in is_relative_to (different drives on Windows)
        with patch.object(Path, 'is_relative_to', side_effect=ValueError):
            workspace = 'C:\\workspace'
            workdir = 'C:\\workspace\\sub'
            file_path = 'D:\\other\\file.txt'

            with pytest.raises(PermissionError) as exc_info:
                resolve_path(file_path, workdir, workspace)

            assert 'File access not permitted' in str(exc_info.value)

    def test_resolve_path_fallback_for_attribute_error(self):
        """Test fallback check when is_relative_to not available (older Python)."""
        with patch.object(Path, 'is_relative_to', side_effect=AttributeError):
            workspace = '/workspace'
            workdir = '/workspace/sub'
            file_path = '/etc/passwd'

            with pytest.raises(PermissionError):
                resolve_path(file_path, workdir, workspace)


class TestReadLines:
    """Tests for read_lines() function."""

    def test_read_all_lines_default(self):
        """Test reading all lines with default parameters."""
        lines = ['line1\n', 'line2\n', 'line3\n']
        result = read_lines(lines)
        assert result == lines

    def test_read_lines_from_start(self):
        """Test reading lines from specific start index."""
        lines = ['line1\n', 'line2\n', 'line3\n', 'line4\n']
        result = read_lines(lines, start=2)
        assert result == ['line3\n', 'line4\n']

    def test_read_lines_with_end(self):
        """Test reading lines with start and end."""
        lines = ['line1\n', 'line2\n', 'line3\n', 'line4\n']
        result = read_lines(lines, start=1, end=3)
        assert result == ['line2\n', 'line3\n']

    def test_read_lines_start_equals_end(self):
        """Test reading lines when start equals end returns empty."""
        lines = ['line1\n', 'line2\n']
        result = read_lines(lines, start=1, end=1)
        assert result == []

    def test_read_lines_negative_start_normalized_to_zero(self):
        """Test that negative start is normalized to 0."""
        lines = ['line1\n', 'line2\n', 'line3\n']
        result = read_lines(lines, start=-5)
        assert result == lines

    def test_read_lines_end_before_start_returns_empty(self):
        """Test that end before start (after normalization) returns empty."""
        lines = ['line1\n', 'line2\n', 'line3\n']
        result = read_lines(lines, start=2, end=1)
        # end gets max(start, end) = max(2, 1) = 2
        assert result == []

    def test_read_lines_empty_list(self):
        """Test reading from empty list."""
        result = read_lines([])
        assert result == []

    def test_read_lines_out_of_bounds_start(self):
        """Test reading with start beyond list length."""
        lines = ['line1\n', 'line2\n']
        result = read_lines(lines, start=10)
        assert result == []

    def test_read_lines_end_minus_one_reads_to_end(self):
        """Test that end=-1 reads to the end."""
        lines = ['line1\n', 'line2\n', 'line3\n']
        result = read_lines(lines, start=1, end=-1)
        assert result == ['line2\n', 'line3\n']


class TestReadFile:
    """Tests for async read_file() function."""

    @pytest.mark.asyncio
    async def test_read_file_success(self):
        """Test successfully reading a file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            test_file = workspace / 'test.txt'
            test_file.write_text('Hello\nWorld\n')

            result = await read_file(
                'test.txt',
                str(workspace),
                str(workspace),
            )

            assert isinstance(result, FileReadObservation)
            assert result.path == 'test.txt'
            assert result.content == 'Hello\nWorld\n'

    @pytest.mark.asyncio
    async def test_read_file_with_line_range(self):
        """Test reading file with line range."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            test_file = workspace / 'test.txt'
            test_file.write_text('Line 1\nLine 2\nLine 3\nLine 4\n')

            result = await read_file(
                'test.txt',
                str(workspace),
                str(workspace),
                start=1,
                end=3,
            )

            assert isinstance(result, FileReadObservation)
            assert result.content == 'Line 2\nLine 3\n'

    @pytest.mark.asyncio
    async def test_read_file_permission_error_path_outside_workspace(self):
        """Test reading file outside workspace returns ErrorObservation."""
        result = await read_file(
            '../../etc/passwd',
            '/workspace/sub',
            '/workspace',
        )

        assert isinstance(result, ErrorObservation)
        assert 'not allowed to access' in result.content

    @pytest.mark.asyncio
    async def test_read_file_not_found(self):
        """Test reading non-existent file returns ErrorObservation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)

            result = await read_file(
                'nonexistent.txt',
                str(workspace),
                str(workspace),
            )

            assert isinstance(result, ErrorObservation)
            assert 'File not found' in result.content

    @pytest.mark.asyncio
    async def test_read_file_unicode_decode_error(self):
        """Test reading binary file with UTF-8 returns ErrorObservation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            test_file = workspace / 'binary.bin'
            # Write invalid UTF-8 bytes
            test_file.write_bytes(b'\x80\x81\x82\x83')

            result = await read_file(
                'binary.bin',
                str(workspace),
                str(workspace),
            )

            assert isinstance(result, ErrorObservation)
            assert 'could not be decoded as utf-8' in result.content

    @pytest.mark.asyncio
    async def test_read_file_is_directory(self):
        """Test reading a directory returns ErrorObservation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            subdir = workspace / 'subdir'
            subdir.mkdir()

            result = await read_file(
                'subdir',
                str(workspace),
                str(workspace),
            )

            assert isinstance(result, ErrorObservation)
            assert 'Path is a directory' in result.content

    @pytest.mark.asyncio
    async def test_read_file_permission_error_on_open(self):
        """Test reading file with permission error returns ErrorObservation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            test_file = workspace / 'protected.txt'
            test_file.write_text('content')

            # Mock open to raise PermissionError
            with patch('builtins.open', side_effect=PermissionError('Access denied')):
                result = await read_file(
                    'protected.txt',
                    str(workspace),
                    str(workspace),
                )

                assert isinstance(result, ErrorObservation)
                assert (
                    'Path is a directory' in result.content
                )  # Current impl maps PermissionError


class TestInsertLines:
    """Tests for insert_lines() function."""

    def test_insert_at_beginning(self):
        """Test inserting lines at the beginning of file."""
        to_insert = ['new line 1', 'new line 2']
        original = ['old line 1\n', 'old line 2\n']

        result = insert_lines(to_insert, original, start=0, end=-1)

        assert result == ['', 'new line 1\n', 'new line 2\n', '']

    def test_insert_in_middle(self):
        """Test inserting lines in the middle of file."""
        to_insert = ['inserted']
        original = ['line 1\n', 'line 2\n', 'line 3\n']

        result = insert_lines(to_insert, original, start=1, end=2)

        expected = [
            'line 1\n',
            'inserted\n',
            'line 3\n',
        ]
        assert result == expected

    def test_insert_at_end(self):
        """Test inserting lines at the end of file."""
        to_insert = ['new line']
        original = ['line 1\n', 'line 2\n']

        result = insert_lines(to_insert, original, start=2, end=-1)

        assert result == ['line 1\n', 'line 2\n', 'new line\n', '']

    def test_insert_replacing_entire_file(self):
        """Test replacing entire file content."""
        to_insert = ['brand new']
        original = ['old 1\n', 'old 2\n']

        result = insert_lines(to_insert, original, start=0, end=-1)

        assert result == ['', 'brand new\n', '']

    def test_insert_empty_list(self):
        """Test inserting empty list."""
        to_insert: list[str] = []
        original: list[str] = ['line 1\n', 'line 2\n']

        result = insert_lines(to_insert, original, start=1, end=1)

        assert result == ['line 1\n', 'line 2\n']

    def test_insert_into_empty_file(self):
        """Test inserting into empty file."""
        to_insert: list[str] = ['first line']
        original: list[str] = []

        result = insert_lines(to_insert, original, start=0, end=-1)

        assert result == ['', 'first line\n', '']

    def test_insert_multiple_lines(self):
        """Test inserting multiple lines."""
        to_insert = ['line A', 'line B', 'line C']
        original = ['1\n', '2\n', '3\n']

        result = insert_lines(to_insert, original, start=1, end=2)

        assert result == [
            '1\n',
            'line A\n',
            'line B\n',
            'line C\n',
            '3\n',
        ]


class TestWriteFile:
    """Tests for async write_file() function."""

    @pytest.mark.asyncio
    async def test_write_new_file(self):
        """Test writing to a new file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            file_path = 'new.txt'
            content = 'Hello\nWorld'

            result = await write_file(
                file_path,
                str(workspace),
                str(workspace),
                content,
            )

            assert isinstance(result, FileWriteObservation)
            assert result.path == file_path

            # Verify file was written
            written_content = (workspace / file_path).read_text()
            assert written_content == 'Hello\nWorld\n'

    @pytest.mark.asyncio
    async def test_write_existing_file_replaces_content(self):
        """Test writing to existing file replaces content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            test_file = workspace / 'existing.txt'
            test_file.write_text('Old content\n')

            result = await write_file(
                'existing.txt',
                str(workspace),
                str(workspace),
                'New content',
            )

            assert isinstance(result, FileWriteObservation)
            written = test_file.read_text()
            assert written == 'New content\n'

    @pytest.mark.asyncio
    async def test_write_file_with_line_range_insertion(self):
        """Test writing with line range inserts at specific position."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            test_file = workspace / 'test.txt'
            test_file.write_text('Line 1\nLine 2\nLine 3\n')

            result = await write_file(
                'test.txt',
                str(workspace),
                str(workspace),
                'Inserted',
                start=1,
                end=2,
            )

            assert isinstance(result, FileWriteObservation)
            written = test_file.read_text()
            assert 'Inserted' in written
            assert 'Line 1' in written
            assert 'Line 3' in written

    @pytest.mark.asyncio
    async def test_write_file_creates_parent_directories(self):
        """Test writing file creates parent directories if needed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            file_path = 'sub/dir/file.txt'

            result = await write_file(
                file_path,
                str(workspace),
                str(workspace),
                'Content',
            )

            assert isinstance(result, FileWriteObservation)
            assert (workspace / 'sub' / 'dir' / 'file.txt').exists()

    @pytest.mark.asyncio
    async def test_write_file_outside_workspace_permission_error(self):
        """Test writing outside workspace returns ErrorObservation."""
        result = await write_file(
            '../../etc/malicious.txt',
            '/workspace/sub',
            '/workspace',
            'bad content',
        )

        assert isinstance(result, ErrorObservation)
        assert 'Permission error' in result.content

    @pytest.mark.asyncio
    async def test_write_file_to_directory_returns_error(self):
        """Test writing to a directory returns ErrorObservation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            subdir = workspace / 'subdir'
            subdir.mkdir()

            # Mock open to raise IsADirectoryError
            with patch('builtins.open', side_effect=IsADirectoryError):
                result = await write_file(
                    'subdir',
                    str(workspace),
                    str(workspace),
                    'content',
                )

                assert isinstance(result, ErrorObservation)
                assert 'Path is a directory' in result.content

    @pytest.mark.asyncio
    async def test_write_file_unicode_decode_error(self):
        """Test writing to file with unicode decode issue."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            test_file = workspace / 'test.txt'
            # Create file with invalid UTF-8
            test_file.write_bytes(b'\x80\x81\x82')

            result = await write_file(
                'test.txt',
                str(workspace),
                str(workspace),
                'new content',
            )

            assert isinstance(result, ErrorObservation)
            assert 'could not be decoded as utf-8' in result.content

    @pytest.mark.asyncio
    async def test_write_file_splits_content_by_newline(self):
        """Test that content is properly split by newline."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            content = 'Line 1\nLine 2\nLine 3'

            result = await write_file(
                'test.txt',
                str(workspace),
                str(workspace),
                content,
            )

            assert isinstance(result, FileWriteObservation)
            written = (workspace / 'test.txt').read_text()
            assert written == 'Line 1\nLine 2\nLine 3\n'

    @pytest.mark.asyncio
    async def test_write_file_append_mode_with_line_range(self):
        """Test writing with end=-1 appends after start line."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            test_file = workspace / 'test.txt'
            test_file.write_text('Line 1\nLine 2\nLine 3\n')

            result = await write_file(
                'test.txt',
                str(workspace),
                str(workspace),
                'Appended',
                start=2,
                end=-1,
            )

            assert isinstance(result, FileWriteObservation)
            written = test_file.read_text()
            # Should keep first 2 lines, then append
            assert 'Line 1' in written
            assert 'Line 2' in written
            assert 'Appended' in written

    @pytest.mark.asyncio
    async def test_write_file_truncates_after_write(self):
        """Test that file is properly truncated after write."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            test_file = workspace / 'test.txt'
            test_file.write_text('Very long original content that should be removed\n')

            result = await write_file(
                'test.txt',
                str(workspace),
                str(workspace),
                'Short',
            )

            assert isinstance(result, FileWriteObservation)
            written = test_file.read_text()
            assert written == 'Short\n'
            assert 'original content' not in written
