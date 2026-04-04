"""Type safety and defensive programming utilities for App.

Provides:
- Sentinel objects for explicit None handling
- Type-safe wrappers
- Path validation utilities
- Defensive programming utilities
"""

from backend.core.type_safety.path_validation import (
    PathValidator,
    SafePath,
    validate_and_sanitize_path,
)
from backend.core.type_safety.sentinels import (
    MISSING,
    NOT_SET,
    Sentinel,
    is_missing,
    is_not_set,
    is_set,
)
from backend.core.type_safety.type_safety import (
    NonEmptyString,
    PositiveInt,
    SafeDict,
    SafeList,
    validate_non_empty_string,
    validate_positive_int,
)

__all__ = [
    # Sentinels
    'MISSING',
    'NOT_SET',
    'Sentinel',
    'is_missing',
    'is_not_set',
    'is_set',
    # Path validation
    'PathValidator',
    'SafePath',
    'validate_and_sanitize_path',
    # Type safety
    'NonEmptyString',
    'PositiveInt',
    'SafeDict',
    'SafeList',
    'validate_non_empty_string',
    'validate_positive_int',
]
