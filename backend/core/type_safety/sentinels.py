"""Sentinel objects for explicit None handling and state management.

Sentinel objects are special marker objects used to distinguish between:
- "Not set" (sentinel) vs "Set to None" (explicit None)
- "Missing" (sentinel) vs "Empty" (empty string/list/etc.)

This prevents bugs where None is used ambiguously and makes code more explicit.
"""

from __future__ import annotations

from typing import Any, TypeVar

T = TypeVar('T')


class Sentinel:
    """Base class for sentinel objects.

    Sentinel objects are used to represent special states that are distinct
    from None. They are singletons and can be used to distinguish between
    "not set" and "set to None".

    Example:
        >>> if value is MISSING:
        ...     # Value was never set
        ... elif value is None:
        ...     # Value was explicitly set to None
        ... else:
        ...     # Value has actual content
    """

    __slots__ = ()

    def __repr__(self) -> str:
        """Return string representation."""
        return f'<{self.__class__.__name__}>'

    def __bool__(self) -> bool:
        """Sentinels are always falsy."""
        return False

    def __eq__(self, other: Any) -> bool:
        """Sentinels only equal themselves."""
        return self is other

    def __hash__(self) -> int:
        """Sentinels are hashable (for use in sets/dicts)."""
        return id(self)


# Global sentinel instances
_MISSING = Sentinel()
_NOT_SET = Sentinel()

# Public API
MISSING: Sentinel = _MISSING
NOT_SET: Sentinel = _NOT_SET


def is_missing(value: Any) -> bool:
    """Check if value is the MISSING sentinel.

    Args:
        value: Value to check

    Returns:
        True if value is MISSING sentinel

    Example:
        >>> value = MISSING
        >>> is_missing(value)
        True
        >>> is_missing(None)
        False
    """
    return value is MISSING


def is_not_set(value: Any) -> bool:
    """Check if value is the NOT_SET sentinel.

    Args:
        value: Value to check

    Returns:
        True if value is NOT_SET sentinel

    Example:
        >>> value = NOT_SET
        >>> is_not_set(value)
        True
        >>> is_not_set(None)
        False
    """
    return value is NOT_SET


def is_set(value: Any) -> bool:
    """Check if value is set (not MISSING or NOT_SET).

    Args:
        value: Value to check

    Returns:
        True if value is set (not a sentinel)

    Example:
        >>> is_set("value")
        True
        >>> is_set(None)
        True  # None is a set value
        >>> is_set(MISSING)
        False
    """
    return value is not MISSING and value is not NOT_SET


def default_if_missing(value: T | Sentinel, default: T) -> T:
    """Return default if value is MISSING, otherwise return value.

    Args:
        value: Value that might be MISSING
        default: Default value to use if MISSING

    Returns:
        value if set, default if MISSING

    Example:
        >>> default_if_missing(MISSING, "default")
        'default'
        >>> default_if_missing("value", "default")
        'value'
        >>> default_if_missing(None, "default")
        None
    """
    return default if is_missing(value) else value  # type: ignore[return-value]


def coalesce[T](*values: T | Sentinel | None) -> T | None:
    """Return first non-sentinel, non-None value.

    Args:
        *values: Values to check

    Returns:
        First non-sentinel, non-None value, or None if all are sentinels/None

    Example:
        >>> coalesce(MISSING, NOT_SET, None, "value")
        'value'
        >>> coalesce(MISSING, None)
        None
    """
    for value in values:
        if is_set(value) and value is not None:
            return value  # type: ignore[return-value]
    return None


# Type aliases for better type hints
type MaybeSentinel[T] = T | Sentinel
type OptionalSentinel[T] = T | None | Sentinel
