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
        block_type = getattr(block, 'type', None)
        if block_type == 'text':
            text_parts.append(block.text)
        elif block_type == 'tool_use':
            tool_calls.append(
                {
                    'id': block.id,
                    'type': 'function',
                    'function': {
                        'name': block.name,
                        'arguments': json.dumps(block.input)
                        if isinstance(block.input, dict)
                        else str(block.input),
                    },
                }
            )
    return '\n'.join(text_parts), tool_calls or None


def _apply_system_cache_control(
    system_content: Any, model: str, kwargs: dict[str, Any]
) -> Any:
    """Return system content with cache_control if the model supports prompt caching.

    When caching is supported, converts a plain string into the list-of-blocks
    format Anthropic requires and adds the ``prompt-caching-2024-07-31`` beta
    header.  Otherwise returns ``system_content`` unchanged.
    """
    from backend.inference.prompt_caching import model_supports_prompt_cache_hints

    if system_content is None:
        return None
    if model_supports_prompt_cache_hints(model):
        text = (
            system_content if isinstance(system_content, str) else str(system_content)
        )
        if 'betas' not in kwargs:
            kwargs['betas'] = ['prompt-caching-2024-07-31']
        return [{'type': 'text', 'text': text, 'cache_control': {'type': 'ephemeral'}}]
    return system_content


def prepare_kwargs(
    messages: list[dict[str, Any]], kwargs: dict[str, Any], default_model: str
) -> tuple[list, dict[str, Any]]:
    """Extract system message and set model for Anthropic calls."""
    system_msg = next((m['content'] for m in messages if m['role'] == 'system'), None)
    filtered = [m for m in messages if m['role'] != 'system']
    if 'model' not in kwargs:
        kwargs['model'] = default_model
    if system_msg is not None:
        model = kwargs.get('model', default_model)
        kwargs['system'] = _apply_system_cache_control(system_msg, model, kwargs)
    # Mark the last tool definition with cache_control so Anthropic caches the
    # entire system + tools prefix.  Tool definitions are stable across turns,
    # making them ideal cache breakpoints (saves 3K-10K input tokens per call).
    _apply_tools_cache_control(kwargs)
    return filtered, kwargs


def _apply_tools_cache_control(kwargs: dict[str, Any]) -> None:
    """Add cache_control to the last tool definition for Anthropic prompt caching.

    Anthropic caches everything up to and including the last block with
    ``cache_control``.  By marking the final tool, the entire system message +
    tool definitions block is cached, saving significant input tokens on
    subsequent calls within the same session.
    """
    from backend.inference.prompt_caching import model_supports_prompt_cache_hints

    tools = kwargs.get('tools')
    if not tools or not isinstance(tools, list):
        return
    model = kwargs.get('model', '')
    if not model_supports_prompt_cache_hints(model):
        return
    last_tool = tools[-1]
    if isinstance(last_tool, dict):
        last_tool['cache_control'] = {'type': 'ephemeral'}
