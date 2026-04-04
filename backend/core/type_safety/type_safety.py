"""Type-safe wrappers and validators for common types.

Provides runtime type validation and safe wrappers that prevent
common bugs and security issues.
"""

from __future__ import annotations

from typing import TypeVar

T = TypeVar('T')


class NonEmptyString(str):
    """String type that cannot be empty.

    This prevents bugs where empty strings are passed where content is expected.

    Example:
        >>> name = NonEmptyString.validate("hello")
        >>> str(name)
        'hello'
        >>> NonEmptyString.validate("")
        ValueError: String cannot be empty
    """

    @classmethod
    def validate(cls, value: str) -> NonEmptyString:
        """Validate and create NonEmptyString.

        Args:
            value: String value

        Returns:
            NonEmptyString instance

        Raises:
            ValueError: If string is empty or whitespace-only
        """
        if not value or not isinstance(value, str):
            raise ValueError('Value must be a non-empty string')
        if not value.strip():
            raise ValueError('String cannot be empty or whitespace-only')
        return cls(value)


class PositiveInt(int):
    """Integer type that must be positive (> 0).

    Example:
        >>> count = PositiveInt.validate(5)
        >>> int(count)
        5
        >>> PositiveInt.validate(-1)
        ValueError: Integer must be positive
    """

    @classmethod
    def validate(cls, value: int) -> PositiveInt:
        """Validate and create PositiveInt.

        Args:
            value: Integer value

        Returns:
            PositiveInt instance

        Raises:
            ValueError: If integer is not positive
        """
        if not isinstance(value, int):
            raise ValueError('Value must be an integer')
        if value <= 0:
            raise ValueError(f'Integer must be positive, got {value}')
        return cls(value)


class SafeList[T](list[T]):
    """List wrapper with bounds checking and safety features.

    Provides safe list operations that prevent index errors and
    provide better error messages.

    Example:
        >>> items = SafeList([1, 2, 3])
        >>> items.safe_get(0)
        1
        >>> items.safe_get(10, default=0)
        0
    """

    def safe_get(self, index: int, default: T | None = None) -> T | None:
        """Safely get item by index with default.

        Args:
            index: Index to get
            default: Default value if index out of bounds

        Returns:
            Item at index or default
        """
        try:
            return self[index]
        except IndexError:
            return default

    def safe_slice(self, start: int, end: int | None = None) -> SafeList[T]:
        """Safely slice list with bounds checking.

        Args:
            start: Start index
            end: End index (optional)

        Returns:
            SafeList slice
        """
        start = max(0, min(start, len(self)))
        if end is not None:
            end = max(start, min(end, len(self)))
        return SafeList(self[start:end])


class SafeDict[T](dict[str, T]):
    """Dictionary wrapper with type safety and safe access.

    Provides safe dictionary operations with better error handling.

    Example:
        >>> data = SafeDict({"key": "value"})
        >>> data.safe_get("key")
        'value'
        >>> data.safe_get("missing", default="default")
        'default'
    """

    def safe_get(self, key: str, default: T | None = None) -> T | None:
        """Safely get value by key with default.

        Args:
            key: Key to get
            default: Default value if key not found

        Returns:
            Value at key or default
        """
        return self.get(key, default)

    def require(self, key: str) -> T:
        """Require a key to exist, raise if missing.

        Args:
            key: Key to require

        Returns:
            Value at key

        Raises:
            KeyError: If key is missing
        """
        if key not in self:
            raise KeyError(f'Required key missing: {key}')
        return self[key]


# Convenience functions
def validate_non_empty_string(value: str, name: str = 'value') -> str:
    """Validate that a string is non-empty.

    Args:
        value: String to validate
        name: Name of the parameter (for error messages)

    Returns:
        Validated string

    Raises:
        ValueError: If string is empty
    """
    if not value or not isinstance(value, str):
        raise ValueError(f'{name} must be a non-empty string')
    if not value.strip():
        raise ValueError(f'{name} cannot be empty or whitespace-only')
    return value


def validate_positive_int(value: int, name: str = 'value') -> int:
    """Validate that an integer is positive.

    Args:
        value: Integer to validate
        name: Name of the parameter (for error messages)

    Returns:
        Validated integer

    Raises:
        ValueError: If integer is not positive
    """
    if not isinstance(value, int):
        raise ValueError(f'{name} must be an integer')
    if value <= 0:
        raise ValueError(f'{name} must be positive, got {value}')
    return value
