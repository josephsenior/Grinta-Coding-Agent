"""Tests for metrics label sanitization utilities."""

from backend.utils.metrics_labels import sanitize_operation_label


class TestSanitizeOperationLabel:
    def test_simple_name(self):
        """Test sanitizing simple alphanumeric name."""
        result = sanitize_operation_label('simple_operation')
        assert result == 'simple_operation'

    def test_name_with_spaces(self):
        """Test sanitizing name with spaces."""
        result = sanitize_operation_label('operation with spaces')
        assert result == 'operation_with_spaces'

    def test_name_with_hyphens(self):
        """Test sanitizing name with hyphens."""
        result = sanitize_operation_label('my-operation-name')
        assert result == 'my_operation_name'

    def test_name_with_dots(self):
        """Test sanitizing name with dots."""
        result = sanitize_operation_label('module.function.name')
        assert result == 'module_function_name'

    def test_name_with_special_chars(self):
        """Test sanitizing name with special characters."""
        result = sanitize_operation_label('operation!@#$%test')
        assert result == 'operation_test'

    def test_consecutive_special_chars(self):
        """Test that consecutive special chars collapse to single underscore."""
        result = sanitize_operation_label('op!!!test')
        assert result == 'op_test'

    def test_leading_trailing_underscores_trimmed(self):
        """Test that leading/trailing underscores are trimmed."""
        result = sanitize_operation_label('__operation__')
        assert result == 'operation'

    def test_max_length_truncation(self):
        """Test that name is truncated to max_length."""
        long_name = 'a' * 150
        result = sanitize_operation_label(long_name, max_length=100)
        assert len(result) == 100

    def test_custom_max_length(self):
        """Test custom max_length parameter."""
        result = sanitize_operation_label('very_long_operation_name', max_length=10)
        assert len(result) <= 10

    def test_none_name(self):
        """Test handling None name."""
        result = sanitize_operation_label(None)
        assert result == 'unknown'

    def test_empty_string(self):
        """Test handling empty string."""
        result = sanitize_operation_label('')
        assert result == 'unknown'

    def test_only_special_chars(self):
        """Test name with only special characters."""
        result = sanitize_operation_label('!@#$%^&*()')
        assert result == 'unknown'

    def test_name_starting_with_digit(self):
        """Test name starting with digit gets prefixed."""
        result = sanitize_operation_label('123operation')
        assert result == 'op_123operation'

    def test_name_starting_with_digit_after_sanitize(self):
        """Test name that starts with digit after sanitization."""
        result = sanitize_operation_label('!123operation')
        assert result == 'op_123operation'

    def test_uppercase_preserved(self):
        """Test that uppercase letters are preserved."""
        result = sanitize_operation_label('MyOperation')
        assert result == 'MyOperation'

    def test_mixed_case(self):
        """Test mixed case name."""
        result = sanitize_operation_label('MyOperation_With_MixedCase')
        assert result == 'MyOperation_With_MixedCase'

    def test_unicode_characters(self):
        """Test handling unicode characters."""
        result = sanitize_operation_label('opération_test')
        # Non-ASCII chars get replaced with underscores
        assert '_' in result

    def test_slash_separator(self):
        """Test slash separator (common in URLs)."""
        result = sanitize_operation_label('api/v1/users')
        assert result == 'api_v1_users'

    def test_colon_separator(self):
        """Test colon separator (common in qualifiers)."""
        result = sanitize_operation_label('module:function')
        assert result == 'module_function'

    def test_parentheses(self):
        """Test parentheses removal."""
        result = sanitize_operation_label('operation(param)')
        assert result == 'operation_param'

    def test_whitespace_only(self):
        """Test string with only whitespace."""
        result = sanitize_operation_label('   \n\t   ')
        assert result == 'unknown'

    def test_default_max_length_100(self):
        """Test default max_length is 100."""
        long_name = 'a' * 200
        result = sanitize_operation_label(long_name)
        assert len(result) == 100

    def test_truncation_removes_trailing_underscores(self):
        """Test that truncation doesn't leave trailing underscores."""
        # Create a name that will have underscore at position 100
        name = 'a' * 99 + '_' + 'b' * 50
        result = sanitize_operation_label(name, max_length=100)
        assert len(result) <= 100
        assert not result.endswith('_')
