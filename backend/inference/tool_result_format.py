"""Single source for structured string-mode tool result blocks in chat history.

Native tool-call transcripts do not use this format. String-mode paths use a
strict JSON envelope wrapped in explicit tags so parsing stays deterministic.
"""

from __future__ import annotations

import json

TOOL_RESULT_BLOCK_PREFIX = "<app_tool_result_json>"
TOOL_RESULT_BLOCK_SUFFIX = "</app_tool_result_json>"


def encode_tool_result_payload(tool_name: str, content: object) -> str:
    """Encode a tool result into the canonical structured text envelope."""
    payload = json.dumps(
        {"tool_name": tool_name, "content": content},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"{TOOL_RESULT_BLOCK_PREFIX}{payload}{TOOL_RESULT_BLOCK_SUFFIX}"


def decode_tool_result_payload(text: str) -> tuple[str, object] | None:
    """Decode strict structured tool result payload from text.

    Returns ``(tool_name, content)`` only when *text* is exactly one encoded
    payload block (ignoring leading/trailing whitespace).
    """
    stripped = (text or "").strip()
    if not (
        stripped.startswith(TOOL_RESULT_BLOCK_PREFIX)
        and stripped.endswith(TOOL_RESULT_BLOCK_SUFFIX)
    ):
        return None

    raw_payload = stripped[
        len(TOOL_RESULT_BLOCK_PREFIX) : len(stripped) - len(TOOL_RESULT_BLOCK_SUFFIX)
    ].strip()
    try:
        parsed = json.loads(raw_payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    tool_name = parsed.get("tool_name")
    if not isinstance(tool_name, str) or not tool_name:
        return None
    return tool_name, parsed.get("content")
