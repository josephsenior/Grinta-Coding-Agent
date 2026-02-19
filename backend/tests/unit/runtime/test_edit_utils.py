"""Tests for pure functions in backend.runtime.utils.edit — _extract_code, _validate_range."""

from __future__ import annotations


import pytest

from backend.runtime.utils.edit import _extract_code


# --------------- _extract_code ---------------


class TestExtractCode:
    def test_extracts_code(self):
        text = "<updated_code>print('hello')</updated_code>"
        assert _extract_code(text) == "print('hello')"

    def test_no_tags_returns_none(self):
        assert _extract_code("no code here") is None

    def test_empty_tags_returns_empty(self):
        assert _extract_code("<updated_code></updated_code>") == ""

    def test_multiline_extraction(self):
        text = "<updated_code>line1\nline2\nline3</updated_code>"
        result = _extract_code(text)
        assert "line1" in result
        assert "line3" in result

    def test_strips_edit_prefix(self):
        text = "<updated_code>#EDIT: foo\nactual code</updated_code>"
        result = _extract_code(text)
        assert result == "actual code"

    def test_surrounding_text_ignored(self):
        text = "Here is the result:\n<updated_code>code</updated_code>\nDone."
        assert _extract_code(text) == "code"

    def test_first_match_returned(self):
        text = "<updated_code>first</updated_code> <updated_code>second</updated_code>"
        assert _extract_code(text) == "first"


# --------------- _validate_range (via FileEditRuntimeMixin) ---------------
# _validate_range is an instance method, so we test it via a minimal subclass


class TestValidateRange:
    """Test _validate_range logic through the mixin."""

    @pytest.fixture
    def mixin(self):
        """Create a minimal concrete implementation for testing."""
        from backend.runtime.utils.edit import FileEditRuntimeMixin

        class _Concrete(FileEditRuntimeMixin):
            def __init__(self):
                self.enable_llm_editor = False
                self.draft_editor_llm = None

            def read(self, action):
                pass

            def write(self, action):
                pass

        return _Concrete()

    def test_valid_range(self, mixin):
        assert mixin._validate_range(1, 10, 20) is None

    def test_valid_single_line(self, mixin):
        assert mixin._validate_range(5, 5, 10) is None

    def test_append_mode(self, mixin):
        assert mixin._validate_range(-1, -1, 10) is None

    def test_start_zero_invalid(self, mixin):
        result = mixin._validate_range(0, 5, 10)
        assert result is not None

    def test_start_beyond_total_invalid(self, mixin):
        result = mixin._validate_range(15, 20, 10)
        assert result is not None

    def test_start_greater_than_end_invalid(self, mixin):
        result = mixin._validate_range(10, 5, 20)
        assert result is not None

    def test_end_beyond_total_invalid(self, mixin):
        result = mixin._validate_range(1, 25, 10)
        assert result is not None

    def test_end_zero_invalid(self, mixin):
        result = mixin._validate_range(1, 0, 10)
        assert result is not None

    def test_end_minus_one_means_until_end(self, mixin):
        assert mixin._validate_range(1, -1, 10) is None
