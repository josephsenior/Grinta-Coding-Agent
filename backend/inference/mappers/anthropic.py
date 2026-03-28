"""Anthropic-specific LLM data adapters and mappers."""

import json
from typing import Any


def extract_tool_calls(
    content_blocks: list,
) -> tuple[str, list[dict[str, Any]] | None]:
    """Extract text and tool_use blocks from Anthropic response content.

    Returns:
        (text_content, tool_calls_or_None)
    """
    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    for block in content_blocks:
        block_type = getattr(block, "type", None)
        if block_type == "text":
            text_parts.append(block.text)
        elif block_type == "tool_use":
            tool_calls.append(
                {
                    "id": block.id,
                    "type": "function",
                    "function": {
                        "name": block.name,
                        "arguments": json.dumps(block.input)
                        if isinstance(block.input, dict)
                        else str(block.input),
                    },
                }
            )
    return "\n".join(text_parts), tool_calls or None


def prepare_kwargs(
    messages: list[dict[str, Any]], kwargs: dict[str, Any], default_model: str
) -> tuple[list, dict[str, Any]]:
    """Extract system message and set model for Anthropic calls."""
    system_msg = next((m["content"] for m in messages if m["role"] == "system"), None)
    filtered = [m for m in messages if m["role"] != "system"]
    if "model" not in kwargs:
        kwargs["model"] = default_model
    if system_msg is not None:
        kwargs["system"] = system_msg
    return filtered, kwargs
