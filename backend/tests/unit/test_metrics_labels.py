"""Tests for backend.utils.metrics_labels — sanitize_operation_label."""

from __future__ import annotations

import pytest

from backend.utils.metrics_labels import sanitize_operation_label


class TestSanitizeOperationLabel:
    """Tests for sanitize_operation_label."""

    def test_simple_name_unchanged(self):
        assert sanitize_operation_label("my_operation") == "my_operation"

    def test_none_returns_unknown(self):
        assert sanitize_operation_label(None) == "unknown"

    def test_empty_returns_unknown(self):
        assert sanitize_operation_label("") == "unknown"

    def test_whitespace_only_returns_unknown(self):
        # spaces → underscores → collapsed → stripped → empty → unknown
        assert sanitize_operation_label("   ") == "unknown"

    def test_special_chars_replaced(self):
        result = sanitize_operation_label("my.operation-name/v2")
        assert "." not in result
        assert "-" not in result
        assert "/" not in result
        # Should be something like "my_operation_name_v2"
        assert result == "my_operation_name_v2"

    def test_consecutive_underscores_collapsed(self):
        result = sanitize_operation_label("a___b")
        assert result == "a_b"

    def test_leading_digit_gets_prefix(self):
        result = sanitize_operation_label("123abc")
        assert result.startswith("op_")
        assert "123abc" in result

    def test_max_length_truncation(self):
        long_name = "a" * 200
        result = sanitize_operation_label(long_name, max_length=50)
        assert len(result) <= 50

    def test_default_max_length(self):
        long_name = "x" * 200
        result = sanitize_operation_label(long_name)
        assert len(result) <= 100

    def test_trailing_underscores_stripped(self):
        # "abc..." → "abc___" → "abc_" → stripped to "abc"
        result = sanitize_operation_label("abc...")
        assert not result.endswith("_")

    def test_mixed_special_and_digits(self):
        result = sanitize_operation_label("3rd-party.lib/call")
        assert result.startswith("op_")  # starts with digit
        assert all(c.isalnum() or c == "_" for c in result)

    def test_non_string_input_coerced(self):
        result = sanitize_operation_label(42)  # type: ignore[arg-type]
        # "42" starts with digit → prefixed with "op_"
        assert result == "op_42"

    def test_unicode_replaced(self):
        result = sanitize_operation_label("héllo_wörld")
        # non-ascii chars replaced with _
        assert all(c.isalnum() or c == "_" for c in result)
