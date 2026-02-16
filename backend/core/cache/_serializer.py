"""Safe JSON-based serialization for Redis cache values.

Uses JSON to eliminate unsafe deserialization attack vectors (CWE-502).
Both ForgeConfig and Settings are Pydantic BaseModel subclasses and
round-trip cleanly through ``model_dump`` → JSON → ``model_validate``.
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, TypeVar

from pydantic import BaseModel, SecretStr

T = TypeVar("T", bound=BaseModel)


def _json_fallback(obj: Any) -> Any:
    """Handle non-JSON-native types produced by Pydantic ``model_dump(mode='python')``."""
    if isinstance(obj, SecretStr):
        return obj.get_secret_value()
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, Path | PurePosixPath | PureWindowsPath):
        return str(obj)
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    if isinstance(obj, set):
        return sorted(obj)
    # Last resort — str() is safer than raising and crashing the cache
    return str(obj)


def serialize_model(model: BaseModel) -> bytes:
    """Serialize a Pydantic model to compact JSON bytes for Redis caching.

    Uses ``model_dump(mode='python')`` so that ``SecretStr`` values are
    preserved (not masked) — required for cache round-tripping.
    """
    data = model.model_dump(mode="python")
    return json.dumps(data, default=_json_fallback, separators=(",", ":")).encode(
        "utf-8"
    )


def deserialize_model[T: BaseModel](raw: bytes, model_class: type[T]) -> T:
    """Deserialize JSON bytes back to a Pydantic model instance."""
    try:
        data = json.loads(raw)
        return model_class.model_validate(data)
    except (json.JSONDecodeError, UnicodeDecodeError):
        msg = f"Cached value for {model_class.__name__} is not valid JSON"
        raise ValueError(msg) from None
