"""Parse LLM wire-format tool ``function.arguments`` strings into dicts."""

from __future__ import annotations

import json
from typing import Any

from json_repair import repair_json


class TruncatedToolArgumentsError(Exception):
    """Raised when tool call arguments appear to have been stream-truncated.

    This happens when the LLM stream ends before the JSON object is closed,
    leaving the arguments as an incomplete JSON string.  The caller should
    treat this as a retriable error rather than silently accepting the partial
    payload.
    """


def parse_tool_arguments_object(raw: object) -> dict[str, Any]:
    """Parse one JSON object from an LLM tool-call arguments string.

    Payloads are first attempted with the stdlib parser.  If that fails and the
    raw text ends with ``}`` (i.e. the object looks structurally complete but has
    bad escapes), ``json_repair`` is applied to recover the payload.

    If the raw text does NOT end with ``}`` the stream was almost certainly cut
    off before the JSON object was closed — in that case a
    ``TruncatedToolArgumentsError`` is raised so that retry machinery can ask
    the model to regenerate the call rather than silently writing truncated file
    content.

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

    # Fast path: if the text is already valid JSON, skip repair entirely.
    try:
        parsed_direct: Any = json.loads(text)
        if isinstance(parsed_direct, dict):
            return parsed_direct
        msg = (
            f'tool arguments must decode to a JSON object, got {type(parsed_direct).__name__}'
        )
        raise TypeError(msg)
    except (json.JSONDecodeError, ValueError):
        pass

    # The text is not valid JSON.  If it looks like a JSON object that started
    # but was never closed (starts with '{', does NOT end with '}'), the stream
    # was most likely cut off mid-value — raise a dedicated error so callers can
    # retry rather than silently accepting a partial payload (e.g. a file that
    # contains only the first few lines of a large create_file body).
    if text.startswith('{') and not text.endswith('}'):
        raise TruncatedToolArgumentsError(
            f'Tool call arguments appear truncated (stream ended before JSON object '
            f'was closed). Last 60 chars: ...{text[-60:]!r}'
        )

    # Text ends with '}' — structurally complete but likely has bad escape
    # sequences.  Apply json_repair to recover the payload.
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
