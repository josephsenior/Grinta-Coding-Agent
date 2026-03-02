"""OpenAI-specific LLM data adapters and mappers."""

from typing import Any


def extract_tool_calls(message: Any) -> list[dict[str, Any]] | None:
    """Extract tool_calls from an OpenAI ChatCompletionMessage."""
    raw = getattr(message, "tool_calls", None)
    if not raw:
        return None
    result: list[dict[str, Any]] = []
    for tc in raw:
        entry: dict[str, Any] = {
            "id": tc.id,
            "type": tc.type,
            "function": {
                "name": tc.function.name,
                "arguments": tc.function.arguments,
            },
        }
        result.append(entry)
    return result or None
