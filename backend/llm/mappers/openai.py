"""OpenAI-specific LLM data adapters and mappers."""

from typing import Any


def extract_tool_calls(message: Any) -> list[dict[str, Any]] | None:
    """Extract tool_calls from an OpenAI ChatCompletionMessage."""
    # New-style tool calling (tool_calls)
    raw = getattr(message, "tool_calls", None)
    if raw:
        result: list[dict[str, Any]] = []
        for tc in raw:
            entry: dict[str, Any] = {
                "id": getattr(tc, "id", None) or "call_0",
                "type": getattr(tc, "type", None) or "function",
                "function": {
                    "name": getattr(getattr(tc, "function", None), "name", ""),
                    "arguments": getattr(getattr(tc, "function", None), "arguments", "{}"),
                },
            }
            result.append(entry)
        return result or None

    # Legacy function calling (function_call) – still used by some OpenAI-compatible APIs.
    fc = getattr(message, "function_call", None)
    if fc is not None:
        name: Any = ""
        arguments: Any = "{}"

        if isinstance(fc, dict):
            name = fc.get("name", "")
            arguments = fc.get("arguments", "{}")
        else:
            name = getattr(fc, "name", "")
            arguments = getattr(fc, "arguments", "{}")

        # Be strict: legacy function_call is only valid when it includes a real
        # function name string. (Prevents truthy placeholders / mocks from
        # being misinterpreted as tool calls.)
        if isinstance(name, str) and name.strip():
            arguments_str = arguments if isinstance(arguments, str) else str(arguments)
            return [
                {
                    "id": "call_0",
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": arguments_str or "{}",
                    },
                }
            ]

    return None
