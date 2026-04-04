"""Compatibility wrapper around stdlib json with optional orjson acceleration.

This module preserves a json-like surface for the common operations used by the
codebase while opportunistically delegating to orjson when the requested call
shape matches capabilities that orjson can satisfy without changing behavior.
"""

from __future__ import annotations

import json as _json
from typing import IO, Any

JSONDecodeError = _json.JSONDecodeError

_orjson: Any = None
_ORJSON_AVAILABLE = False

try:
    import orjson as _orjson_module
except Exception:  # pragma: no cover - optional dependency import guard
    pass
else:
    _orjson = _orjson_module
    _ORJSON_AVAILABLE = True


_COMPACT_SEPARATORS = (',', ':')


def _can_use_orjson(
    *,
    ensure_ascii: bool,
    indent: int | None,
    separators: tuple[str, str] | None,
    cls: type[Any] | None,
    kwargs: dict[str, Any],
) -> bool:
    if not _ORJSON_AVAILABLE:
        return False
    if ensure_ascii:
        return False
    if indent not in (None, 2):
        return False
    if separators is not None and tuple(separators) != _COMPACT_SEPARATORS:
        return False
    if cls is not None:
        return False
    if kwargs:
        return False
    return True


def dumps(
    obj: Any,
    *,
    skipkeys: bool = False,
    ensure_ascii: bool = True,
    check_circular: bool = True,
    allow_nan: bool = True,
    cls: type[Any] | None = None,
    indent: int | None = None,
    separators: tuple[str, str] | None = None,
    default: Any = None,
    sort_keys: bool = False,
    **kwargs: Any,
) -> str:
    """Serialize *obj* to JSON, using orjson when it can match behavior."""
    if skipkeys or not check_circular or not allow_nan:
        return _json.dumps(
            obj,
            skipkeys=skipkeys,
            ensure_ascii=ensure_ascii,
            check_circular=check_circular,
            allow_nan=allow_nan,
            cls=cls,
            indent=indent,
            separators=separators,
            default=default,
            sort_keys=sort_keys,
            **kwargs,
        )

    if _can_use_orjson(
        ensure_ascii=ensure_ascii,
        indent=indent,
        separators=separators,
        cls=cls,
        kwargs=kwargs,
    ):
        orjson_module = _orjson
        option = orjson_module.OPT_NON_STR_KEYS
        if sort_keys:
            option |= orjson_module.OPT_SORT_KEYS
        if indent == 2:
            option |= orjson_module.OPT_INDENT_2
        return orjson_module.dumps(obj, default=default, option=option).decode('utf-8')

    return _json.dumps(
        obj,
        skipkeys=skipkeys,
        ensure_ascii=ensure_ascii,
        check_circular=check_circular,
        allow_nan=allow_nan,
        cls=cls,
        indent=indent,
        separators=separators,
        default=default,
        sort_keys=sort_keys,
        **kwargs,
    )


def dump(obj: Any, fp: IO[str], **kwargs: Any) -> None:
    """Serialize *obj* to a file-like object."""
    fp.write(dumps(obj, **kwargs))


def loads(data: str | bytes | bytearray | memoryview, **kwargs: Any) -> Any:
    """Deserialize JSON text or bytes."""
    if _ORJSON_AVAILABLE and not kwargs:
        return _orjson.loads(data)
    return _json.loads(data, **kwargs)


def load(fp: IO[str], **kwargs: Any) -> Any:
    """Deserialize JSON from a file-like object."""
    return loads(fp.read(), **kwargs)
