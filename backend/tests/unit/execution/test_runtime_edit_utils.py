"""Tests for backend.execution.utils.edit — pure helper functions and FileEditRuntimeMixin."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.execution.utils.edit import (
    _extract_code,
    FileEditRuntimeMixin,
)


# ── _extract_code ─────────────────────────────────────────────────────


class TestExtractCode:
    def test_extracts_code_from_tags(self):
        response = "Some text <updated_code>print('hello')</updated_code> more text"
        result = _extract_code(response)
        assert result == "print('hello')"

    def test_returns_none_when_no_tags(self):
        assert _extract_code("no tags here") is None

    def test_handles_multiline_code(self):
        code = "line1\nline2\nline3"
        response = f"<updated_code>{code}</updated_code>"
        assert _extract_code(response) == code

    def test_strips_edit_prefix(self):
        response = "<updated_code>#EDIT: some comment\nactual code</updated_code>"
        assert _extract_code(response) == "actual code"

    def test_first_match_when_multiple_tags(self):
        response = (
            "<updated_code>first</updated_code> <updated_code>second</updated_code>"
        )
        assert _extract_code(response) == "first"

    def test_empty_tags(self):
        response = "<updated_code></updated_code>"
        result = _extract_code(response)
        assert result == ""


# ── _validate_range (via mixin) ───────────────────────────────────────


class _ConcreteEditor(FileEditRuntimeMixin):
    """Concrete subclass to test mixin methods."""

    def __init__(self):
        self.config = MagicMock()
        self.runtime = MagicMock()
        self.draft_editor_llm = None
        self.enable_llm_editor = False

    def read(self, action):
        return MagicMock()

    def write(self, action):
        return MagicMock()


class TestValidateRange:
    def setup_method(self):
        self.editor = _ConcreteEditor()

    def test_valid_range(self):
        assert self.editor._validate_range(1, 10, 20) is None

    def test_start_equals_end(self):
        assert self.editor._validate_range(5, 5, 10) is None

    def test_start_zero_invalid(self):
        result = self.editor._validate_range(0, 5, 10)
        assert result is not None

    def test_start_exceeds_total(self):
        result = self.editor._validate_range(11, 11, 10)
        assert result is not None

    def test_start_greater_than_end(self):
        result = self.editor._validate_range(5, 3, 10)
        assert result is not None

    def test_end_exceeds_total(self):
        result = self.editor._validate_range(1, 11, 10)
        assert result is not None

    def test_end_zero_invalid(self):
        result = self.editor._validate_range(1, 0, 10)
        assert result is not None

    def test_append_mode_start_minus_one(self):
        result = self.editor._validate_range(-1, -1, 10)
        assert result is None

    def test_start_equals_total(self):
        assert self.editor._validate_range(10, 10, 10) is None


# ── _calculate_edit_range ─────────────────────────────────────────────


class TestCalculateEditRange:
    def setup_method(self):
        self.editor = _ConcreteEditor()

    def test_normal_range(self):
        action = MagicMock()
        action.start = 3
        action.end = 7
        start_idx, end_idx, length = self.editor._calculate_edit_range(
            action, [""] * 20
        )
        assert start_idx == 2
        assert end_idx == 7
        assert length == 5

    def test_end_minus_one_means_end_of_file(self):
        action = MagicMock()
        action.start = 1
        action.end = -1
        lines = [""] * 10
        start_idx, end_idx, length = self.editor._calculate_edit_range(action, lines)
        assert start_idx == 0
        assert end_idx == 10
        assert length == 10


# ── check_retry_num ───────────────────────────────────────────────────


class TestCheckRetryNum:
    def test_returns_true_when_exceeded(self):
        editor = _ConcreteEditor()
        editor.draft_editor_llm = MagicMock()
        editor.draft_editor_llm.config.correct_num = 3
        assert editor.check_retry_num(4) is True

    def test_returns_false_when_within(self):
        editor = _ConcreteEditor()
        editor.draft_editor_llm = MagicMock()
        editor.draft_editor_llm.config.correct_num = 3
        assert editor.check_retry_num(2) is False

    def test_returns_false_at_boundary(self):
        editor = _ConcreteEditor()
        editor.draft_editor_llm = MagicMock()
        editor.draft_editor_llm.config.correct_num = 3
        assert editor.check_retry_num(3) is False

    def test_raises_when_no_llm(self):
        editor = _ConcreteEditor()
        with pytest.raises(RuntimeError, match="disabled"):
            editor.check_retry_num(1)
