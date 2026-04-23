"""Parse LLM wire-format tool ``function.arguments`` strings into dicts."""

from __future__ import annotations

import json
from typing import Any

from json_repair import repair_json


def parse_tool_arguments_object(raw: object) -> dict[str, Any]:
    """Parse one JSON object from an LLM tool-call arguments string.

    Payloads always go through ``json_repair`` then ``json.loads`` — one path.
    Models often emit bad escapes inside embedded code; repair fixes the common
    cases so the stdlib parser can load the result.

    Deterministic *authoring*: use ``json.dumps`` on a structured ``dict`` when
    generating tool JSON programmatically — that is guaranteed valid JSON. LLM
    output is only as reliable as the model; this layer is deterministic for a
    given input string (same bytes in, same parsed dict out).
    """
    if not isinstance(raw, str):
        msg = f'tool arguments must be a string, got {type(raw).__name__}'
        raise TypeError(msg)
    text = raw.strip()
    if not text:
        raise ValueError('tool arguments string is empty')

    repaired: Any = repair_json(text)
    if isinstance(repaired, tuple):
        repaired = repaired[0] if repaired else text
    repaired_str = str(repaired).strip()

    parsed: Any = json.loads(repaired_str)
    if not isinstance(parsed, dict):
        msg = (
            f'tool arguments must decode to a JSON object, got {type(parsed).__name__}'
        )
        raise TypeError(msg)
    return parsed
