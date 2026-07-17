"""Unit tests for atomic file replace helper."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.persistence.file_store.atomic_write import (
    _make_writable,
    replace_file_with_retry,
)


def test_make_writable_success(tmp_path: Path) -> None:
    test_file = tmp_path / "test.txt"
    test_file.write_text("hello")
    # Make it writable (should not raise)
    _make_writable(str(test_file))
    assert test_file.read_text() == "hello"


def test_make_writable_oserror() -> None:
    # Trigger OSError and ensure it is caught (does not raise)
    with patch("os.chmod", side_effect=OSError("Permission denied")):
        _make_writable("nonexistent_file_path")


def test_replace_file_with_retry_success(tmp_path: Path) -> None:
    temp_file = tmp_path / "temp.txt"
    dest_file = tmp_path / "dest.txt"

    temp_file.write_text("new content")
    dest_file.write_text("old content")

    replace_file_with_retry(temp_file, dest_file)

    assert dest_file.read_text() == "new content"
    assert not temp_file.exists()


def test_replace_file_with_retry_filenotfound(tmp_path: Path) -> None:
    temp_file = tmp_path / "nonexistent.txt"
    dest_file = tmp_path / "dest.txt"

    with pytest.raises(FileNotFoundError):
        replace_file_with_retry(temp_file, dest_file)


def test_replace_file_with_retry_permission_error_retries_and_succeeds(tmp_path: Path) -> None:
    temp_file = tmp_path / "temp.txt"
    dest_file = tmp_path / "dest.txt"

    temp_file.write_text("new content")
    dest_file.write_text("old content")

    original_replace = os.replace
    call_count = 0

    def mock_replace(src: str, dst: str) -> None:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise PermissionError("Access denied (mocked)")
        # Actual replace on 3rd attempt using original reference
        original_replace(src, dst)

    with patch("os.replace", side_effect=mock_replace):
        replace_file_with_retry(temp_file, dest_file)
        assert call_count == 3
        assert dest_file.read_text() == "new content"


def test_replace_file_with_retry_permission_error_exhausted(tmp_path: Path) -> None:
    temp_file = tmp_path / "temp.txt"
    dest_file = tmp_path / "dest.txt"

    temp_file.write_text("new content")
    dest_file.write_text("old content")

    with patch("os.replace", side_effect=PermissionError("Always locked")):
        with pytest.raises(PermissionError) as exc:
            replace_file_with_retry(temp_file, dest_file)
        assert "Always locked" in str(exc.value)


def test_replace_file_with_retry_os_error_exhausted(tmp_path: Path) -> None:
    temp_file = tmp_path / "temp.txt"
    dest_file = tmp_path / "dest.txt"

    temp_file.write_text("new content")
    dest_file.write_text("old content")

    with patch("os.replace", side_effect=OSError("Disk full")):
        with pytest.raises(OSError) as exc:
            replace_file_with_retry(temp_file, dest_file)
        assert "Disk full" in str(exc.value)
