"""Tests for backend.runtime.utils.git_changes — git change parsing."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.runtime.utils.git_changes import (
    _normalize_status,
    _parse_git_status_line,
)


# ---------------------------------------------------------------------------
# _parse_git_status_line
# ---------------------------------------------------------------------------

class TestParseGitStatusLine:
    def test_modified_file(self):
        result = _parse_git_status_line("M\tsrc/main.py", [])
        assert result == [{"status": "M", "path": "src/main.py"}]

    def test_added_file(self):
        result = _parse_git_status_line("A\tnew_file.py", [])
        assert result == [{"status": "A", "path": "new_file.py"}]

    def test_deleted_file(self):
        result = _parse_git_status_line("D\told_file.py", [])
        assert result == [{"status": "D", "path": "old_file.py"}]

    def test_renamed_file(self):
        result = _parse_git_status_line("R100\told.py\tnew.py", [])
        assert len(result) == 2
        assert result[0] == {"status": "D", "path": "old.py"}
        assert result[1] == {"status": "A", "path": "new.py"}

    def test_copied_file(self):
        result = _parse_git_status_line("C100\toriginal.py\tcopy.py", [])
        assert len(result) == 1
        assert result[0] == {"status": "A", "path": "copy.py"}

    def test_untracked_file(self):
        result = _parse_git_status_line("??\tuntracked.py", [])
        assert result == [{"status": "A", "path": "untracked.py"}]

    def test_empty_line_raises(self):
        with pytest.raises(RuntimeError, match="unexpected_value"):
            _parse_git_status_line("", [])

    def test_single_token_raises(self):
        with pytest.raises(RuntimeError, match="unexpected_value"):
            _parse_git_status_line("M", [])


# ---------------------------------------------------------------------------
# _normalize_status
# ---------------------------------------------------------------------------

class TestNormalizeStatus:
    def test_question_marks_to_added(self):
        result = _normalize_status("??", "file.py", [])
        assert result == {"status": "A", "path": "file.py"}

    def test_star_to_modified(self):
        result = _normalize_status("*", "file.py", [])
        assert result == {"status": "M", "path": "file.py"}

    def test_valid_statuses(self):
        for s in ["M", "A", "D", "U"]:
            result = _normalize_status(s, "f.py", [])
            assert result["status"] == s

    def test_unknown_status_raises(self):
        with pytest.raises(RuntimeError, match="unexpected_status"):
            _normalize_status("X", "file.py", [])
