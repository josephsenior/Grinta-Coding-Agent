"""JSON serialization/deserialization helpers with Forge-specific encoding."""

import json
from datetime import datetime
from typing import Any

from json_repair import repair_json
from pydantic import BaseModel

from backend.core.errors import LLMResponseError
from backend.core.pydantic_compat import model_dump_with_options
from backend.events.event import Event
from backend.events.observation import CmdOutputMetadata
from backend.events.serialization import event_to_dict
from backend.llm.metrics import Metrics


class ForgeJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder that handles datetime and event objects."""

    def default(self, obj: Any) -> Any:
        """Serialize Forge-specific objects when dumping JSON."""
        result = _try_serialize_forge_object(obj)
        if result is not _NOT_SERIALIZED:
            return result
        return super().default(obj)


_NOT_SERIALIZED = object()


def _try_serialize_forge_object(obj: Any) -> Any:
    """Serialize Forge-specific types; return _NOT_SERIALIZED if not handled."""
    handlers = (
        (datetime, lambda o: o.isoformat()),
        (Event, event_to_dict),
        (Metrics, lambda o: o.get()),
        ((BaseModel, CmdOutputMetadata), model_dump_with_options),
    )
    for types_or_type, fn in handlers:
        if isinstance(obj, types_or_type):
            return fn(obj)
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return _NOT_SERIALIZED


_json_encoder = ForgeJSONEncoder()


def dumps(obj: Any, **kwargs: Any) -> str:
    """Serialize an object to str format."""
    if not kwargs:
        return _json_encoder.encode(obj)
    encoder_kwargs = kwargs.copy()
    if "cls" not in encoder_kwargs:
        encoder_kwargs["cls"] = ForgeJSONEncoder
    return json.dumps(obj, **encoder_kwargs)


def loads(json_str: str, **kwargs: Any) -> Any:
    """Create a JSON object from str."""
    try:
        return json.loads(json_str, **kwargs)
    except json.JSONDecodeError:
        pass
    extracted = _extract_first_json_object(json_str)
    if extracted is not None:
        return _repair_and_load(extracted, kwargs)
    raise LLMResponseError("No valid JSON object found in response.")


def _extract_first_json_object(json_str: str) -> str | None:
    """Extract first complete {...} object from string using brace matching."""
    depth = 0
    start = -1
    for i, char in enumerate(json_str):
        depth, start = _update_brace_depth(char, depth, start, i)
        if depth == 0 and start >= 0:
            return json_str[start : i + 1]
    return None


def _update_brace_depth(char: str, depth: int, start: int, i: int) -> tuple[int, int]:
    """Update depth and start index when scanning for JSON object."""
    if char == "{":
        return depth + 1, i if depth == 0 else start
    if char == "}":
        return depth - 1, start
    return depth, start


def _repair_and_load(extracted: str, kwargs: dict) -> Any:
    """Attempt to repair malformed JSON and load."""
    try:
        repaired_raw: Any = repair_json(extracted)
        if isinstance(repaired_raw, tuple):
            repaired_val: Any = repaired_raw[0] if repaired_raw else extracted
        else:
            repaired_val = repaired_raw
        return json.loads(str(repaired_val), **kwargs)
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        raise LLMResponseError(
            "Invalid JSON in response. Please make sure the response is a valid JSON object."
        ) from e


__all__ = ["ForgeJSONEncoder", "dumps", "loads"]
