"""JSON serialization/deserialization helpers with Forge-specific encoding."""

import json
from datetime import datetime
from typing import Any

from json_repair import repair_json
from pydantic import BaseModel

from backend.core.exceptions import LLMResponseError
from backend.core.pydantic_compat import model_dump_with_options
from backend.events.event import Event
from backend.events.observation import CmdOutputMetadata
from backend.events.serialization import event_to_dict
from backend.llm.metrics import Metrics


class ForgeJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder that handles datetime and event objects."""

    def default(self, obj: Any) -> Any:
        """Serialize Forge-specific objects when dumping JSON."""
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, Event):
            return event_to_dict(obj)
        if isinstance(obj, Metrics):
            return obj.get()
        if isinstance(obj, BaseModel | CmdOutputMetadata):
            return model_dump_with_options(obj)
        # Handle dict-like objects that might have been ModelResponse or similar
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
        return super().default(obj)


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
    depth = 0
    start = -1
    for i, char in enumerate(json_str):
        if char == "{":
            if depth == 0:
                start = i
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0 and start != -1:
                response = json_str[start : i + 1]
                try:
                    json_str = repair_json(response)
                    return json.loads(json_str, **kwargs)
                except (json.JSONDecodeError, ValueError, TypeError) as e:
                    msg = "Invalid JSON in response. Please make sure the response is a valid JSON object."
                    raise LLMResponseError(
                        msg,
                    ) from e
    msg = "No valid JSON object found in response."
    raise LLMResponseError(msg)


__all__ = ["ForgeJSONEncoder", "dumps", "loads"]
