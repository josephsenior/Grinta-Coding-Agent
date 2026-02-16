"""Tests for backend.core.type_safety.type_safety — type-safe wrappers and validators."""

import pytest

from backend.core.type_safety.type_safety import (
    NonEmptyString,
    PositiveInt,
    SafeDict,
    SafeList,
    validate_non_empty_string,
    validate_positive_int,
)


class TestNonEmptyString:
    """Tests for NonEmptyString class."""

    def test_validate_valid_string(self):
        """Test validating a valid non-empty string."""
        result = NonEmptyString.validate("hello")
        assert result == "hello"
        assert isinstance(result, NonEmptyString)

    def test_validate_empty_string_raises(self):
        """Test validating empty string raises ValueError."""
        with pytest.raises(ValueError, match="non-empty string"):
            NonEmptyString.validate("")

    def test_validate_whitespace_only_raises(self):
        """Test validating whitespace-only string raises ValueError."""
        with pytest.raises(ValueError, match="whitespace-only"):
            NonEmptyString.validate("   ")

    def test_validate_non_string_raises(self):
        """Test validating non-string raises ValueError."""
        with pytest.raises(ValueError, match="non-empty string"):
            NonEmptyString.validate(123)  # type: ignore

    def test_validate_none_raises(self):
        """Test validating None raises ValueError."""
        with pytest.raises(ValueError, match="non-empty string"):
            NonEmptyString.validate(None)  # type: ignore

    def test_str_conversion(self):
        """Test converting NonEmptyString to str."""
        result = NonEmptyString.validate("test")
        assert str(result) == "test"

    def test_string_operations(self):
        """Test NonEmptyString supports string operations."""
        result = NonEmptyString.validate("hello")
        assert result.upper() == "HELLO"
        assert result + " world" == "hello world"


class TestPositiveInt:
    """Tests for PositiveInt class."""

    def test_validate_positive_integer(self):
        """Test validating a positive integer."""
        result = PositiveInt.validate(5)
        assert result == 5
        assert isinstance(result, PositiveInt)

    def test_validate_one(self):
        """Test validating 1 (minimum positive)."""
        result = PositiveInt.validate(1)
        assert result == 1

    def test_validate_large_number(self):
        """Test validating large positive integer."""
        result = PositiveInt.validate(999999)
        assert result == 999999

    def test_validate_zero_raises(self):
        """Test validating zero raises ValueError."""
        with pytest.raises(ValueError, match="must be positive"):
            PositiveInt.validate(0)

    def test_validate_negative_raises(self):
        """Test validating negative integer raises ValueError."""
        with pytest.raises(ValueError, match="must be positive"):
            PositiveInt.validate(-1)

    def test_validate_non_integer_raises(self):
        """Test validating non-integer raises ValueError."""
        with pytest.raises(ValueError, match="must be an integer"):
            PositiveInt.validate("5")  # type: ignore

    def test_int_conversion(self):
        """Test converting PositiveInt to int."""
        result = PositiveInt.validate(10)
        assert int(result) == 10

    def test_arithmetic_operations(self):
        """Test PositiveInt supports arithmetic operations."""
        result = PositiveInt.validate(5)
        assert result + 3 == 8
        assert result * 2 == 10


class TestSafeList:
    """Tests for SafeList class."""

    def test_create_safe_list(self):
        """Test creating SafeList."""
        safe_list = SafeList([1, 2, 3])
        assert len(safe_list) == 3
        assert safe_list[0] == 1

    def test_safe_get_valid_index(self):
        """Test safe_get with valid index."""
        safe_list = SafeList([1, 2, 3])
        result = safe_list.safe_get(1)
        assert result == 2

    def test_safe_get_out_of_bounds_returns_none(self):
        """Test safe_get with out of bounds index returns None."""
        safe_list = SafeList([1, 2, 3])
        result = safe_list.safe_get(10)
        assert result is None

    def test_safe_get_with_default(self):
        """Test safe_get with custom default."""
        safe_list = SafeList([1, 2, 3])
        result = safe_list.safe_get(10, default=0)
        assert result == 0

    def test_safe_get_negative_index(self):
        """Test safe_get with negative index."""
        safe_list = SafeList([1, 2, 3])
        result = safe_list.safe_get(-1)
        assert result == 3

    def test_safe_slice_valid_range(self):
        """Test safe_slice with valid range."""
        safe_list = SafeList([1, 2, 3, 4, 5])
        result = safe_list.safe_slice(1, 3)
        assert result == [2, 3]
        assert isinstance(result, SafeList)

    def test_safe_slice_out_of_bounds(self):
        """Test safe_slice with out of bounds range."""
        safe_list = SafeList([1, 2, 3])
        result = safe_list.safe_slice(1, 100)
        assert result == [2, 3]

    def test_safe_slice_negative_start(self):
        """Test safe_slice with negative start is clamped."""
        safe_list = SafeList([1, 2, 3])
        result = safe_list.safe_slice(-10, 2)
        assert result == [1, 2]

    def test_safe_slice_no_end(self):
        """Test safe_slice without end parameter."""
        safe_list = SafeList([1, 2, 3, 4])
        result = safe_list.safe_slice(2)
        assert result == [3, 4]

    def test_safe_slice_start_after_end(self):
        """Test safe_slice where start > end."""
        safe_list = SafeList([1, 2, 3])
        result = safe_list.safe_slice(2, 1)
        assert result == []

    def test_list_operations(self):
        """Test SafeList supports standard list operations."""
        safe_list = SafeList([1, 2, 3])
        safe_list.append(4)
        assert len(safe_list) == 4
        assert safe_list[-1] == 4


class TestSafeDict:
    """Tests for SafeDict class."""

    def test_create_safe_dict(self):
        """Test creating SafeDict."""
        safe_dict = SafeDict({"key": "value"})
        assert len(safe_dict) == 1
        assert safe_dict["key"] == "value"

    def test_safe_get_existing_key(self):
        """Test safe_get with existing key."""
        safe_dict = SafeDict({"key": "value"})
        result = safe_dict.safe_get("key")
        assert result == "value"

    def test_safe_get_missing_key_returns_none(self):
        """Test safe_get with missing key returns None."""
        safe_dict = SafeDict({"key": "value"})
        result = safe_dict.safe_get("missing")
        assert result is None

    def test_safe_get_with_default(self):
        """Test safe_get with custom default."""
        safe_dict = SafeDict({"key": "value"})
        result = safe_dict.safe_get("missing", default="default")
        assert result == "default"

    def test_require_existing_key(self):
        """Test require with existing key."""
        safe_dict = SafeDict({"key": "value"})
        result = safe_dict.require("key")
        assert result == "value"

    def test_require_missing_key_raises(self):
        """Test require with missing key raises KeyError."""
        safe_dict = SafeDict({"key": "value"})
        with pytest.raises(KeyError, match="Required key missing: missing"):
            safe_dict.require("missing")

    def test_dict_operations(self):
        """Test SafeDict supports standard dict operations."""
        safe_dict = SafeDict({"a": 1})
        safe_dict["b"] = 2
        assert len(safe_dict) == 2
        assert "a" in safe_dict
        assert "c" not in safe_dict


class TestValidateNonEmptyString:
    """Tests for validate_non_empty_string function."""

    def test_validate_valid_string(self):
        """Test validating a valid string."""
        result = validate_non_empty_string("hello")
        assert result == "hello"

    def test_validate_empty_string_raises(self):
        """Test validating empty string raises ValueError."""
        with pytest.raises(ValueError, match="must be a non-empty string"):
            validate_non_empty_string("")

    def test_validate_whitespace_only_raises(self):
        """Test validating whitespace-only string raises ValueError."""
        with pytest.raises(ValueError, match="whitespace-only"):
            validate_non_empty_string("   ")

    def test_validate_non_string_raises(self):
        """Test validating non-string raises ValueError."""
        with pytest.raises(ValueError, match="must be a non-empty string"):
            validate_non_empty_string(123)  # type: ignore

    def test_validate_none_raises(self):
        """Test validating None raises ValueError."""
        with pytest.raises(ValueError, match="must be a non-empty string"):
            validate_non_empty_string(None)  # type: ignore

    def test_custom_name_in_error(self):
        """Test custom parameter name appears in error message."""
        with pytest.raises(ValueError, match="username must be a non-empty string"):
            validate_non_empty_string("", name="username")

    def test_custom_name_whitespace_error(self):
        """Test custom name in whitespace error."""
        with pytest.raises(ValueError, match="password cannot be empty"):
            validate_non_empty_string("   ", name="password")


class TestValidatePositiveInt:
    """Tests for validate_positive_int function."""

    def test_validate_positive_integer(self):
        """Test validating a positive integer."""
        result = validate_positive_int(5)
        assert result == 5

    def test_validate_one(self):
        """Test validating 1."""
        result = validate_positive_int(1)
        assert result == 1

    def test_validate_large_number(self):
        """Test validating large number."""
        result = validate_positive_int(1000000)
        assert result == 1000000

    def test_validate_zero_raises(self):
        """Test validating zero raises ValueError."""
        with pytest.raises(ValueError, match="must be positive"):
            validate_positive_int(0)

    def test_validate_negative_raises(self):
        """Test validating negative integer raises ValueError."""
        with pytest.raises(ValueError, match="must be positive"):
            validate_positive_int(-5)

    def test_validate_non_integer_raises(self):
        """Test validating non-integer raises ValueError."""
        with pytest.raises(ValueError, match="must be an integer"):
            validate_positive_int(3.14)  # type: ignore

    def test_custom_name_in_error(self):
        """Test custom parameter name appears in error message."""
        with pytest.raises(ValueError, match="count must be an integer"):
            validate_positive_int("not an int", name="count")  # type: ignore

    def test_custom_name_positive_error(self):
        """Test custom name in positive error."""
        with pytest.raises(ValueError, match="timeout must be positive"):
            validate_positive_int(-1, name="timeout")
