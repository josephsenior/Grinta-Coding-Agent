"""Utilities for adapting tool schemas to specific LLM provider constraints."""

import copy
from typing import Any

from backend.core.config import LLMConfig
from backend.core.logger import app_logger as logger
from backend.core.message import Message


def check_tools(tools: list[dict], llm_config: LLMConfig) -> list[dict]:
    """Checks and modifies tools for compatibility with the current LLM.

    Args:
        tools: List of tool parameters
        llm_config: LLM configuration

    Returns:
        Modified tools compatible with the LLM

    """
    if not llm_config.model or 'gemini' not in llm_config.model.lower():
        return tools

    logger.info(
        'Removing default fields and unsupported formats from tools for Gemini model %s '
        "since Gemini models have limited format support (only 'enum' and 'date-time' for STRING types).",
        llm_config.model,
    )

    return _clean_tools_for_gemini(tools)


def _clean_tools_for_gemini(
    tools: list[dict],
) -> list[dict]:
    """Remove unsupported fields and formats for Gemini models.

    Args:
        tools: List of tool parameters

    Returns:
        Cleaned tools

    """
    checked_tools = copy.deepcopy(tools)

    for tool in checked_tools:
        if 'function' in tool and 'parameters' in tool['function']:
            if 'properties' in tool['function']['parameters']:
                _clean_tool_properties(tool['function']['parameters']['properties'])

    return checked_tools


def _clean_tool_properties(properties: dict) -> None:
    """Clean tool properties for Gemini compatibility.

    Args:
        properties: Tool properties dict (modified in place)

    """
    for prop_name, prop in properties.items():
        # Remove default values
        if 'default' in prop:
            del prop['default']

        # Remove unsupported string formats
        if prop.get('type') == 'string' and 'format' in prop:
            if prop['format'] not in ['enum', 'date-time']:
                logger.info(
                    'Removing unsupported format "%s" for STRING parameter "%s"',
                    prop['format'],
                    prop_name,
                )
                del prop['format']


def get_token_count(
    messages: list[dict] | list[Message],
    model: str = 'gpt-4o',
    custom_tokenizer: Any = None,
) -> int:
    """Standalone function to estimate token count."""
    if custom_tokenizer is not None:
        # If we have a custom tokenizer, we should ideally use it
        # But for now we just fallback to the simple estimation
        pass

    text = ''
    for m in messages:
        if isinstance(m, dict):
            content = m.get('content', '')
        else:
            content = getattr(m, 'content', '')

        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    text += str(part.get('text', ''))
                else:
                    text += str(getattr(part, 'text', ''))
        else:
            text += str(content)

    return max(1, len(text) // 4)


def create_pretrained_tokenizer(name: str) -> Any:
    """Placeholder for tokenizer creation.

    Kept as a patch point for tests.
    """
    return name
