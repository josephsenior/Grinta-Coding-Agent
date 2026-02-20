"""Tests for backend.runtime.file_operations — file read/write/resolve/encode helpers."""

from __future__ import annotations

import base64
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from backend.runtime.file_operations import (
    _format_directory_listing,
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
    truncate_large_text,
    write_file_content,
)
from backend.events.action import FileReadAction, FileWriteAction


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
        val, err = _parse_insert_line("42")
        assert val == 42 and err is None

    def test_str_invalid(self):
        val, err = _parse_insert_line("abc")
        assert val is None
        assert "Invalid insert_line" in err


# ---------------------------------------------------------------------------
# truncate_large_text
# ---------------------------------------------------------------------------
class TestTruncateLargeText:
    def test_no_truncation_needed(self):
        assert truncate_large_text("short", 100, label="test") == "short"

    def test_truncation(self):
        big = "x" * 200
        result = truncate_large_text(big, 50, label="test")
        assert "Truncated by Forge" in result
        assert len(result) < 200

    def test_max_chars_zero(self):
        assert truncate_large_text("hello", 0, label="test") == "hello"


# ---------------------------------------------------------------------------
# get_max_edit_observation_chars
# ---------------------------------------------------------------------------
class TestGetMaxEditObservationChars:
    def test_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FORGE_MAX_EDIT_OBS_CHARS", None)
            assert get_max_edit_observation_chars() == 200000

    def test_custom_value(self):
        with patch.dict(os.environ, {"FORGE_MAX_EDIT_OBS_CHARS": "5000"}):
            assert get_max_edit_observation_chars() == 5000

    def test_invalid_value(self):
        with patch.dict(os.environ, {"FORGE_MAX_EDIT_OBS_CHARS": "abc"}):
            assert get_max_edit_observation_chars() == 200000

    def test_negative_value(self):
        with patch.dict(os.environ, {"FORGE_MAX_EDIT_OBS_CHARS": "-1"}):
            assert get_max_edit_observation_chars() == 200000


# ---------------------------------------------------------------------------
# encode_binary_file
# ---------------------------------------------------------------------------
class TestEncodeBinaryFile:
    def test_basic_encoding(self):
        data = b"hello world"
        result = encode_binary_file("/tmp/test.png", data, "image/png", "image/png")
        assert result.startswith("data:image/png;base64,")
        encoded_part = result.split(",", 1)[1]
        assert base64.b64decode(encoded_part) == data

    def test_none_mime_uses_default(self):
        result = encode_binary_file(
            "/tmp/test", b"data", None, "application/octet-stream"
        )
        assert "application/octet-stream" in result


# ---------------------------------------------------------------------------
# resolve_path
# ---------------------------------------------------------------------------
class TestResolvePath:
    def test_relative_path(self):
        with tempfile.TemporaryDirectory() as td:
            # Create the file so validation passes
            with open(os.path.join(td, "test.txt"), "w", encoding="utf-8") as f:
                f.write("test")
            result = resolve_path("test.txt", td)
            assert os.path.isabs(result)
            assert result.endswith("test.txt")


# ---------------------------------------------------------------------------
# ensure_directory_exists
# ---------------------------------------------------------------------------
class TestEnsureDirectoryExists:
    def test_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as td:
            deep = os.path.join(td, "a", "b", "c", "file.txt")
            ensure_directory_exists(deep)
            assert os.path.isdir(os.path.join(td, "a", "b", "c"))

    def test_empty_parent(self):
        # No error for just a filename
        ensure_directory_exists("test.txt")


# ---------------------------------------------------------------------------
# read_text_file
# ---------------------------------------------------------------------------
class TestReadTextFile:
    def test_full_file(self):
        with tempfile.NamedTemporaryFile(
            "w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write("line1\nline2\nline3\n")
            f.flush()
            action = FileReadAction(path=f.name)
            obs = read_text_file(f.name, action)
            assert "line1" in obs.content
            assert "line3" in obs.content
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
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"\x89PNG\r\n\x1a\n")
            f.flush()
            obs = read_image_file(f.name)
            assert obs.content.startswith("data:image/png;base64,")
        os.unlink(f.name)

    def test_read_pdf(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-1.4")
            f.flush()
            obs = read_pdf_file(f.name)
            assert "application/pdf" in obs.content
        os.unlink(f.name)

    def test_read_video(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(b"\x00\x00\x00\x1cftyp")
            f.flush()
            obs = read_video_file(f.name)
            assert "video/mp4" in obs.content
        os.unlink(f.name)


# ---------------------------------------------------------------------------
# handle_file_read_errors
# ---------------------------------------------------------------------------
class TestHandleFileReadErrors:
    def test_file_not_found(self):
        obs = handle_file_read_errors("/nonexistent/path.txt", "/nonexistent")
        assert "not found" in obs.content.lower() or "Cannot read" in obs.content

    def test_file_exists_permission_error(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            obs = handle_file_read_errors(f.name, os.path.dirname(f.name))
            assert "Cannot read" in obs.content or "permission" in obs.content.lower()
        os.unlink(f.name)


# ---------------------------------------------------------------------------
# write_file_content
# ---------------------------------------------------------------------------
class TestWriteFileContent:
    def test_write_new_file(self):
        with tempfile.TemporaryDirectory() as td:
            fp = os.path.join(td, "new.txt")
            action = FileWriteAction(path=fp, content="hello world")
            err = write_file_content(fp, action, file_exists=False)
            assert err is None
            assert open(fp, encoding="utf-8").read() == "hello world"

    def test_write_error_returns_observation(self):
        # Try writing to a directory
        with tempfile.TemporaryDirectory() as td:
            action = FileWriteAction(path=td, content="test")
            err = write_file_content(td, action, file_exists=False)
            assert err is not None
            assert "Failed" in err.content


# ---------------------------------------------------------------------------
# set_file_permissions
# ---------------------------------------------------------------------------
class TestSetFilePermissions:
    def test_windows_noop(self):
        # On Windows, this is a noop
        with patch("backend.runtime.file_operations.os.name", "nt"):
            set_file_permissions("/tmp/test", False, None)  # Should not raise


# ---------------------------------------------------------------------------
# execute_file_editor
# ---------------------------------------------------------------------------
class TestExecuteFileEditor:
    def test_successful_edit(self):
        result_mock = MagicMock()
        result_mock.error = None
        result_mock.output = "File edited successfully"
        result_mock.old_content = "old"
        result_mock.new_content = "new"
        editor = MagicMock(return_value=result_mock)

        output, (old, new) = execute_file_editor(editor, "str_replace", "/test.py")
        assert output == "File edited successfully"
        assert old == "old"
        assert new == "new"

    def test_editor_error(self):
        result_mock = MagicMock()
        result_mock.error = "Something went wrong"
        result_mock.output = ""
        editor = MagicMock(return_value=result_mock)

        output, (old, new) = execute_file_editor(editor, "str_replace", "/test.py")
        assert "ERROR" in output
        assert old is None and new is None

    def test_invalid_insert_line(self):
        editor = MagicMock()
        output, (old, new) = execute_file_editor(
            editor, "insert", "/test.py", insert_line="abc"
        )
        assert "Invalid insert_line" in output
        editor.assert_not_called()


# ---------------------------------------------------------------------------
# _list_directory_recursive / _format_directory_listing / handle_directory_view
# ---------------------------------------------------------------------------
class TestDirectoryViewing:
    def test_list_directory_recursive(self):
        with tempfile.TemporaryDirectory() as td:
            # Create structure
            os.makedirs(os.path.join(td, "subdir"))
            # Corrected: open args and context manager
            with open(os.path.join(td, "file1.txt"), "w", encoding="utf-8") as f: f.write("f1")
            with open(os.path.join(td, "subdir", "file2.txt"), "w", encoding="utf-8") as f: f.write("f2")
            with open(os.path.join(td, ".hidden"), "w", encoding="utf-8") as f: f.write("h")

            entries, hidden = _list_directory_recursive(td, max_depth=2)
            assert any("file1.txt" in e for e in entries)
            assert any("file2.txt" in e for e in entries)
            assert hidden >= 1  # .hidden

    def test_format_directory_listing(self):
        files = ["subdir/", "file1.txt", "subdir/file2.txt"]
        result = _format_directory_listing("/workspace", files, 1)
        assert "/workspace" in result
        assert "hidden" in result.lower()

    def test_handle_directory_view(self):
        with tempfile.TemporaryDirectory() as td:
            with open(os.path.join(td, "readme.md"), "w", encoding="utf-8") as f:
                f.write("test")
            obs = handle_directory_view(td, "/workspace")
            assert "readme.md" in obs.content
