"""Tests for backend.execution.aes.file_operations — file read/write/resolve/encode helpers."""

from __future__ import annotations

import base64
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from backend.execution.aes.file_operations import (
    _DIFF_TRUNC_HARD_CAP,
    DIFF_CODEC_MARKER_PREFIX,
    _format_directory_listing,
    _get_max_cmd_output_chars,
    _list_directory_recursive,
    _parse_insert_line,
    encode_binary_file,
    ensure_directory_exists,
    execute_file_editor,
    get_max_edit_observation_chars,
    handle_directory_view,
    handle_file_read_errors,
    read_image_file,
    read_pdf_file,
    read_text_file,
    read_video_file,
    resolve_path,
    set_file_permissions,
    truncate_cmd_output,
    truncate_diff,
    truncate_large_text,
)
from backend.ledger.action import FileReadAction
from backend.ledger.observation import FileReadObservation


# ---------------------------------------------------------------------------
# _parse_insert_line
# ---------------------------------------------------------------------------
class TestParseInsertLine:
    def test_none_passthrough(self):
        val, err = _parse_insert_line(None)
        assert val is None and err is None

    def test_int_passthrough(self):
        val, err = _parse_insert_line(5)
        assert val == 5 and err is None

    def test_str_valid(self):
        val, err = _parse_insert_line('42')
        assert val == 42 and err is None

    def test_str_invalid(self):
        val, err = _parse_insert_line('abc')
        assert val is None
        assert err is not None and 'Invalid insert_line' in err


# ---------------------------------------------------------------------------
# truncate_large_text
# ---------------------------------------------------------------------------
class TestTruncateLargeText:
    def test_no_truncation_needed(self):
        assert truncate_large_text('short', 100, label='test') == 'short'

    def test_truncation(self):
        big = 'x' * 200
        result = truncate_large_text(big, 50, label='test')
        assert 'Truncated by app' in result
        assert len(result) < 200

    def test_max_chars_zero(self):
        assert truncate_large_text('hello', 0, label='test') == 'hello'


class TestTruncateDiff:
    def test_small_diff_unchanged(self):
        diff = 'diff --git a/x b/x\n+added line\n-removed line\n'
        assert truncate_diff(diff) == diff

    def test_large_diff_inserts_structured_marker(self):
        diff = '\n'.join(f'+line-{i}' for i in range(20000))
        result = truncate_diff(diff, path='src/big.py')
        assert len(result) < len(diff)
        assert DIFF_CODEC_MARKER_PREFIX in result

    def test_large_diff_marker_without_path(self):
        diff = 'x' * (_DIFF_TRUNC_HARD_CAP + 5000)
        result = truncate_diff(diff)
        assert DIFF_CODEC_MARKER_PREFIX in result

    def test_truncation_snaps_to_line_boundaries(self):
        diff = '\n'.join(f'+line-{i:05d}' for i in range(20000))
        result = truncate_diff(diff, path='f.py')
        for line in result.splitlines():
            if line.startswith('+line-'):
                assert len(line) == len('+line-00000'), (
                    f'mid-line cut produced fragment: {line!r}'
                )

    def test_priority_drops_context_before_changes(self):
        """Context lines should be dropped before +/- lines."""
        lines = ['diff --git a/foo b/foo', '--- a/foo', '+++ b/foo']
        for i in range(500):
            lines.append(f'@@ -{i * 10 + 1},5 +{i * 10 + 1},5 @@')
            lines.append(f' context line {i} before')
            lines.append(f'+added line {i}')
            lines.append(f'-removed line {i}')
            lines.append(f' context line {i} after')
            lines.append(f' far context line {i}')
        diff = '\n'.join(lines)
        result = truncate_diff(diff, path='foo')
        # Context lines should be dropped first; most changes should survive
        add_count = sum(1 for line in result.splitlines() if line.startswith('+added'))
        remove_count = sum(
            1 for line in result.splitlines() if line.startswith('-removed')
        )
        assert add_count > 100, f'Only {add_count} additions survived (expected >100)'
        assert remove_count > 100, (
            f'Only {remove_count} removals survived (expected >100)'
        )
        # Far context (non-adjacent) should be entirely dropped
        far_ctx = sum(
            1 for line in result.splitlines() if line.startswith(' far context')
        )
        assert far_ctx == 0, f'{far_ctx} far context lines survived (expected 0)'

    def test_hunk_headers_always_preserved_in_truncated_mode(self):
        """@@ headers must survive even when their content is dropped."""
        lines = ['diff --git a/foo b/foo', '--- a/foo', '+++ b/foo']
        # 400 hunks: headers ~16k chars, content ~24k chars → headers fit, content doesn't
        for i in range(400):
            lines.append(f'@@ -{i + 1},2 +{i + 1},2 @@')
            lines.append(f'+change {i} with some extra text to make it longer')
            lines.append(f' context {i} with some padding text here')
        diff = '\n'.join(lines)
        result = truncate_diff(diff, path='foo')
        header_count = sum(1 for line in result.splitlines() if line.startswith('@@'))
        assert header_count == 400, (
            f'Only {header_count} hunk headers survived (expected 400)'
        )

    def test_fidelity_summary_emitted_when_truncated(self):
        """The fidelity summary must be present when truncation occurs."""
        lines = ['diff --git a/foo b/foo', '--- a/foo', '+++ b/foo']
        # 300 hunks: headers ~7.5k, content ~18k → truncated (context dropped)
        for i in range(300):
            lines.append(f'@@ -{i + 1},3 +{i + 1},3 @@')
            lines.append(f' context line with some padding text {i}')
            lines.append(f'+change line with some padding text {i}')
        diff = '\n'.join(lines)
        result = truncate_diff(diff, path='foo')
        assert '[DIFF_CODEC' in result
        assert 'mode=truncated' in result
        assert 'change_line_coverage=' in result

    def test_fidelity_summary_not_emitted_for_small_diff(self):
        """Small diffs under the cap should pass through unchanged."""
        diff = 'diff --git a/x b/x\n+added\n-removed\n'
        assert truncate_diff(diff) == diff

    def test_skeleton_mode_for_huge_metadata(self):
        """When structural metadata alone exceeds budget, emit skeleton."""
        # Create a diff with many files so headers exceed 20k
        lines = []
        for i in range(2000):
            lines.append(
                f'diff --git a/file_{i:04d}_with_long_name.py b/file_{i:04d}_with_long_name.py'
            )
            lines.append('index abc..def 100644')
            lines.append(f'--- a/file_{i:04d}_with_long_name.py')
            lines.append(f'+++ b/file_{i:04d}_with_long_name.py')
            lines.append('@@ -1,1 +1,1 @@')
            lines.append(f'+change {i}')
        diff = '\n'.join(lines)
        result = truncate_diff(diff)
        assert '[SKELETON:' in result
        assert 'mode=skeleton' in result
        # Skeleton should have file headers but no +/- content
        assert 'diff --git' in result

    def test_original_order_preserved(self):
        """Surviving lines must appear in original diff order."""
        lines = ['diff --git a/foo b/foo', '--- a/foo', '+++ b/foo']
        for i in range(800):
            lines.append(f'@@ -{i + 1},5 +{i + 1},5 @@')
            lines.append(f' ctx before {i}')
            lines.append(f'+add {i}')
            lines.append(f'-rem {i}')
            lines.append(f' ctx after {i}')
            lines.append(f' far context {i}')
        diff = '\n'.join(lines)
        result = truncate_diff(diff, path='foo')
        result_lines = [
            line for line in result.splitlines() if line.startswith('+add ')
        ]
        indices = [int(line.split()[1]) for line in result_lines]
        assert indices == sorted(indices), 'Lines not in original order'

    def test_generated_file_hunks_collapsed(self):
        """Generated file hunks should not compete for main budget."""
        lines = ['diff --git a/package-lock.json b/package-lock.json']
        lines.append('--- a/package-lock.json')
        lines.append('+++ b/package-lock.json')
        for i in range(100):
            lines.append(f'@@ -{i * 100 + 1},50 +{i * 100 + 1},50 @@')
            for j in range(50):
                lines.append(f'+{"x" * 80}')
        lines.append('diff --git a/main.py b/main.py')
        lines.append('--- a/main.py')
        lines.append('+++ b/main.py')
        lines.append('@@ -1,3 +1,3 @@')
        lines.append(' ctx')
        lines.append('+important change')
        lines.append(' ctx')
        diff = '\n'.join(lines)
        result = truncate_diff(diff)
        # The important change in main.py should survive
        assert '+important change' in result


class TestTruncateCmdOutput:
    def test_truncate_cmd_output_head_tail_notice(self):
        output = ''.join(f'line-{i}\n' for i in range(200))
        truncated = truncate_cmd_output(output, max_chars=300)
        assert '[APP: Output truncated' in truncated
        assert 'line-0' in truncated
        assert 'line-199' in truncated

    def test_get_max_cmd_output_chars_reads_app_env(self):
        with patch.dict(os.environ, {'APP_MAX_CMD_OUTPUT_CHARS': '1234'}):
            assert _get_max_cmd_output_chars(None) == 1234


# ---------------------------------------------------------------------------
# Issue #1: CmdOutputObservation.__init__ must NOT pre-truncate
# ---------------------------------------------------------------------------
class TestCmdOutputObservationNoInitTruncation:
    """Verify that CmdOutputObservation does NOT truncate content in __init__.

    Previously __init__ called _maybe_truncate (now removed) at a hardcoded
    10 000 chars, making the env-configurable truncate_cmd_output (40 000)
    a no-op.  Truncation is now owned by the execution layer
    (truncate_cmd_output) and the processor layer (truncate_content).
    """

    def test_init_does_not_truncate_large_content(self):
        from backend.ledger.observation import CmdOutputObservation

        large = 'x' * 50_000
        obs = CmdOutputObservation(content=large, command='test')
        assert len(obs.content) == 50_000, (
            'CmdOutputObservation.__init__ must not pre-truncate; '
            'truncate_cmd_output is the primary truncator'
        )

    def test_init_preserves_content_below_old_cap(self):
        """Content >10 000 (old MAX_CMD_OUTPUT_SIZE) must pass through."""
        from backend.ledger.observation import CmdOutputObservation

        content = 'x' * 15_000
        obs = CmdOutputObservation(content=content, command='test')
        assert len(obs.content) == 15_000

    def test_truncate_cmd_output_is_effective_at_env_default(self):
        """truncate_cmd_output at 40 000 chars must actually truncate
        content that would have been pre-capped at 10 000 before.
        """
        output = ''.join(f'line-{i:05d}-padding\n' for i in range(5000))
        assert len(output) > 40_000
        truncated = truncate_cmd_output(output)
        assert '[APP: Output truncated' in truncated
        assert len(truncated) < len(output)


# ---------------------------------------------------------------------------
# get_max_edit_observation_chars
# ---------------------------------------------------------------------------
class TestGetMaxEditObservationChars:
    def test_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('APP_MAX_EDIT_OBS_CHARS', None)
            assert get_max_edit_observation_chars() == 500000

    def test_custom_value(self):
        with patch.dict(os.environ, {'APP_MAX_EDIT_OBS_CHARS': '5000'}):
            assert get_max_edit_observation_chars() == 5000

    def test_invalid_value(self):
        with patch.dict(os.environ, {'APP_MAX_EDIT_OBS_CHARS': 'abc'}):
            assert get_max_edit_observation_chars() == 500000

    def test_negative_value(self):
        with patch.dict(os.environ, {'APP_MAX_EDIT_OBS_CHARS': '-1'}):
            assert get_max_edit_observation_chars() == 500000


# ---------------------------------------------------------------------------
# encode_binary_file
# ---------------------------------------------------------------------------
class TestEncodeBinaryFile:
    def test_basic_encoding(self):
        data = b'hello world'
        result = encode_binary_file('/tmp/test.png', data, 'image/png', 'image/png')
        assert result.startswith('data:image/png;base64,')
        encoded_part = result.split(',', 1)[1]
        assert base64.b64decode(encoded_part) == data

    def test_none_mime_uses_default(self):
        result = encode_binary_file(
            '/tmp/test', b'data', None, 'application/octet-stream'
        )
        assert 'application/octet-stream' in result


# ---------------------------------------------------------------------------
# resolve_path
# ---------------------------------------------------------------------------
class TestResolvePath:
    def test_relative_path(self):
        with tempfile.TemporaryDirectory() as td:
            # Create the file so validation passes
            with open(os.path.join(td, 'test.txt'), 'w', encoding='utf-8') as f:
                f.write('test')
            result = resolve_path('test.txt', td)
            assert os.path.isabs(result)
            assert result.endswith('test.txt')


# ---------------------------------------------------------------------------
# ensure_directory_exists
# ---------------------------------------------------------------------------
class TestEnsureDirectoryExists:
    def test_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as td:
            deep = os.path.join(td, 'a', 'b', 'c', 'file.txt')
            ensure_directory_exists(deep)
            assert os.path.isdir(os.path.join(td, 'a', 'b', 'c'))

    def test_empty_parent(self):
        # No error for just a filename
        ensure_directory_exists('test.txt')


# ---------------------------------------------------------------------------
# read_text_file
# ---------------------------------------------------------------------------
class TestReadTextFile:
    def test_full_file(self):
        with tempfile.NamedTemporaryFile(
            'w', suffix='.txt', delete=False, encoding='utf-8'
        ) as f:
            f.write('line1\nline2\nline3\n')
            f.flush()
            action = FileReadAction(path=f.name)
            obs = read_text_file(f.name, action)
            assert 'line1' in obs.content
            assert 'line3' in obs.content
        os.unlink(f.name)

    def test_directory_raises(self):
        with tempfile.TemporaryDirectory() as td:
            action = FileReadAction(path=td)
            with pytest.raises(IsADirectoryError):
                read_text_file(td, action)


# ---------------------------------------------------------------------------
# read_image_file / read_pdf_file / read_video_file
# ---------------------------------------------------------------------------
class TestBinaryFileReaders:
    def test_read_image(self):
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            f.write(b'\x89PNG\r\n\x1a\n')
            f.flush()
            obs = read_image_file(f.name)
            assert obs.content.startswith('data:image/png;base64,')
        os.unlink(f.name)

    def test_read_pdf(self):
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
            f.write(b'%PDF-1.4')
            f.flush()
            obs = read_pdf_file(f.name)
            assert 'application/pdf' in obs.content
        os.unlink(f.name)

    def test_read_video(self):
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as f:
            f.write(b'\x00\x00\x00\x1cftyp')
            f.flush()
            obs = read_video_file(f.name)
            assert 'video/mp4' in obs.content
        os.unlink(f.name)


# ---------------------------------------------------------------------------
# handle_file_read_errors
# ---------------------------------------------------------------------------
class TestHandleFileReadErrors:
    def test_file_not_found(self):
        obs = handle_file_read_errors('/nonexistent/path.txt', '/nonexistent')
        assert 'not found' in obs.content.lower() or 'Cannot read' in obs.content

    def test_file_exists_permission_error(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            obs = handle_file_read_errors(f.name, os.path.dirname(f.name))
            assert 'Cannot read' in obs.content or 'permission' in obs.content.lower()
        os.unlink(f.name)


# ---------------------------------------------------------------------------
# set_file_permissions
# ---------------------------------------------------------------------------
class TestSetFilePermissions:
    def test_windows_noop(self):
        # On Windows, this is a noop
        with patch('backend.execution.aes.file_operations.os.name', 'nt'):
            set_file_permissions('/tmp/test', False, None)  # Should not raise


# ---------------------------------------------------------------------------
# execute_file_editor
# ---------------------------------------------------------------------------
class TestExecuteFileEditor:
    def test_successful_edit(self):
        result_mock = MagicMock()
        result_mock.error = None
        result_mock.output = 'File edited successfully'
        result_mock.old_content = 'old'
        result_mock.new_content = 'new'
        result_mock.error_code = None
        result_mock.retryable = False
        result_mock.operation = 'edit'
        result_mock.metadata = {}
        editor = MagicMock(return_value=result_mock)

        output, (old, new), tool_result = execute_file_editor(
            editor, 'edit', '/test.py'
        )
        assert output == 'File edited successfully'
        assert old == 'old'
        assert new == 'new'
        assert tool_result['ok'] is True

    def test_editor_error(self):
        result_mock = MagicMock()
        result_mock.error = 'Something went wrong'
        result_mock.error_code = 'EDITOR_ERROR'
        result_mock.retryable = False
        result_mock.operation = 'edit'
        result_mock.metadata = {}
        result_mock.output = ''
        editor = MagicMock(return_value=result_mock)

        output, (old, new), tool_result = execute_file_editor(
            editor, 'edit', '/test.py'
        )
        assert 'edit failed' in output or 'Something went wrong' in output
        assert old is None and new is None
        assert tool_result['ok'] is False
        assert tool_result['error_code'] == 'EDITOR_ERROR'
        assert 'payload' not in tool_result

    def test_invalid_insert_line(self):
        editor = MagicMock()
        output, (old, new), tool_result = execute_file_editor(
            editor, 'insert_text', '/test.py', insert_line='abc'
        )
        assert 'Invalid insert_line' in output
        assert tool_result['error_code'] == 'INVALID_INSERT_LINE'
        editor.assert_not_called()


# ---------------------------------------------------------------------------
# _list_directory_recursive / _format_directory_listing / handle_directory_view
# ---------------------------------------------------------------------------
class TestDirectoryViewing:
    def test_list_directory_recursive(self):
        with tempfile.TemporaryDirectory() as td:
            # Create structure
            os.makedirs(os.path.join(td, 'subdir'))
            # Corrected: open args and context manager
            with open(os.path.join(td, 'file1.txt'), 'w', encoding='utf-8') as f:
                f.write('f1')
            with open(
                os.path.join(td, 'subdir', 'file2.txt'), 'w', encoding='utf-8'
            ) as f:
                f.write('f2')
            with open(os.path.join(td, '.hidden'), 'w', encoding='utf-8') as f:
                f.write('h')

            entries, hidden = _list_directory_recursive(td, max_depth=2)
            assert any('file1.txt' in e for e in entries)
            assert any('file2.txt' in e for e in entries)
            assert hidden >= 1  # .hidden

    def test_format_directory_listing(self):
        files = ['subdir/', 'file1.txt', 'subdir/file2.txt']
        result = _format_directory_listing('/workspace', files, 1)
        assert '/workspace' in result
        assert 'hidden' in result.lower()

    def test_format_directory_listing_windows_hidden_hint(self):
        files = ['subdir/', 'file1.txt']
        with patch('backend.execution.aes.file_operations.OS_CAPS') as mock_caps:
            mock_caps.is_windows = True
            result = _format_directory_listing('/workspace', files, 1)

        assert 'Get-ChildItem -Force /workspace' in result
        assert 'ls -la' not in result

    def test_handle_directory_view(self):
        with tempfile.TemporaryDirectory() as td:
            with open(os.path.join(td, 'readme.md'), 'w', encoding='utf-8') as f:
                f.write('test')
            obs = handle_directory_view(td, '/workspace')
            assert isinstance(obs, FileReadObservation)
            assert 'readme.md' in obs.content
