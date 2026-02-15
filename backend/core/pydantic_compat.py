"""Pydantic compatibility helpers.

Provides small utility functions to safely serialize Pydantic models and
inspect model fields in a way that works across Pydantic v1 and v2.
"""

from __future__ import annotations

import json
from typing import Any


def model_to_dict(obj: Any) -> Any:
    """Return a plain Python structure for a Pydantic model or passthrough for others.

    Prefer Pydantic v2's `model_dump`, fall back to v1's `dict`, then to
    json roundtrip, and finally return the object itself as a last resort.
    """
    try:
        if hasattr(obj, "model_dump") and callable(obj.model_dump):
            return obj.model_dump()
    except Exception:
        pass
    try:
        if hasattr(obj, "dict") and callable(obj.dict):
            return obj.dict()
    except Exception:
        pass
    try:
        return json.loads(json.dumps(obj, default=str))
    except Exception:
        return obj


def _try_get_v2_model_fields(model_cls: Any) -> set[str] | None:
    """Try to get field names from Pydantic v2 model_fields."""
    try:
        mf = getattr(model_cls, "model_fields", None)
        if mf and isinstance(mf, dict):
            return set(mf.keys())
    except Exception:
        pass
    return None


def _try_get_v1_model_fields(model_cls: Any) -> set[str] | None:
    """Try to get field names from Pydantic v1 __fields__."""
    try:
        if hasattr(model_cls, "__fields__"):
            return set(model_cls.__fields__.keys())
    except Exception:
        pass
    return None


def _get_annotations_fallback(model_cls: Any) -> set[str]:
    """Get field names from __annotations__ as last resort."""
    return set(getattr(model_cls, "__annotations__", {}).keys())


def get_model_field_names(model_cls: Any) -> set[str]:
    """Return a set of field names for a Pydantic model class across versions.

    Accepts the model class (not instance). Tries v2's `model_fields`, then
    v1's `__fields__`, then `__annotations__` as a last resort.
    """
    # Try Pydantic v2 model_fields
    v2_fields = _try_get_v2_model_fields(model_cls)
    if v2_fields is not None:
        return v2_fields

    # Try Pydantic v1 __fields__
    v1_fields = _try_get_v1_model_fields(model_cls)
    return _get_annotations_fallback(model_cls) if v1_fields is None else v1_fields


def _try_model_dump(obj: Any, **kwargs) -> tuple[bool, Any]:
    """Try to call Pydantic v2's model_dump method."""
    try:
        md = getattr(obj, "model_dump", None)
        if md and callable(md):
            return True, obj.model_dump(**kwargs)
    except Exception:
        pass
    return False, None


def _try_json_dump(obj: Any, **kwargs) -> tuple[bool, Any]:
    """Try to call Pydantic v1's json method with mode='json'."""
    try:
        mode = kwargs.get("mode")
        if mode == "json":
            j = getattr(obj, "json", None)
            if j and callable(j):
                filtered_kwargs = {k: v for k, v in kwargs.items() if k != "mode"}
                return True, json.loads(obj.json(**filtered_kwargs))
    except Exception:
        pass
    return False, None


def _try_dict_dump(obj: Any, **kwargs) -> tuple[bool, Any]:
    """Try to call Pydantic v1's dict method."""
    try:
        d = getattr(obj, "dict", None)
        if d and callable(d):
            filtered_kwargs = {k: v for k, v in kwargs.items() if k != "mode"}
            return True, obj.dict(**filtered_kwargs)
    except Exception:
        pass
    return False, None


def model_dump_with_options(obj: Any, **kwargs) -> Any:
    """Call a model's dump method with kwargs in a version-compatible way.

    Prefer Pydantic v2's `model_dump(**kwargs)`. If unavailable, fall back to
    v1's `dict(**kwargs)` or `json(**kwargs)` when appropriate. As a last
    resort use `model_to_dict` which does a best-effort conversion.
    """
    success, result = _try_model_dump(obj, **kwargs)
    if success:
        return result

    success, result = _try_json_dump(obj, **kwargs)
    if success:
        return result

    success, result = _try_dict_dump(obj, **kwargs)
    return result if success else model_to_dict(obj)


def model_dump_json(obj: Any, **kwargs) -> str:
    """Return a JSON string representation compatible with v2/v1 models.

    Prefer `model_dump_json` (v2), then `json()` (v1), then JSON-dump of
    `model_dump_with_options`/`model_to_dict`.
    """
    try:
        mdj = getattr(obj, "model_dump_json", None)
        if mdj and callable(mdj):
            return obj.model_dump_json(**kwargs)
    except Exception:
        pass
    try:
        j = getattr(obj, "json", None)
        if j and callable(j):
            return obj.json(**kwargs)
    except Exception:
        pass
    try:
        data = model_dump_with_options(
            obj, **{k: v for k, v in kwargs.items() if k != "mode"}
        )
        return json.dumps(data, default=str)
    except Exception:
        return json.dumps(model_to_dict(obj), default=str)
