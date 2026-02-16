"""Tests for backend.utils.metrics_labels — sanitize_operation_label extra coverage."""

from __future__ import annotations

import pytest

from backend.utils.metrics_labels import sanitize_operation_label


class TestSanitizeOperationLabelUnit:
    def test_none_input(self):
        assert sanitize_operation_label(None) == "unknown"

    def test_empty_string(self):
        assert sanitize_operation_label("") == "unknown"

    def test_simple_alphanumeric(self):
        assert sanitize_operation_label("my_op") == "my_op"

    def test_special_chars_to_underscore(self):
        assert sanitize_operation_label("a.b-c/d") == "a_b_c_d"

    def test_collapse_consecutive_underscores(self):
        assert sanitize_operation_label("x___y") == "x_y"

    def test_strip_leading_trailing_underscores(self):
        assert sanitize_operation_label("__foo__") == "foo"

    def test_max_length_truncation(self):
        long = "a" * 200
        result = sanitize_operation_label(long, max_length=50)
        assert len(result) <= 50

    def test_default_max_length(self):
        long = "a" * 200
        result = sanitize_operation_label(long)
        assert len(result) <= 100

    def test_digit_prefix_gets_op(self):
        result = sanitize_operation_label("42_foo")
        assert result == "op_42_foo"

    def test_all_special_chars_gives_unknown(self):
        assert sanitize_operation_label("!!@@##") == "unknown"

    def test_preserves_underscores(self):
        assert sanitize_operation_label("a_b_c") == "a_b_c"
