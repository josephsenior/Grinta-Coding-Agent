"""Utilities for adapting tool schemas to specific LLM provider constraints."""

import copy
from functools import lru_cache
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
    payload = _messages_to_token_payload(messages)
    if not payload:
        return 1

    tokenizer = _resolve_tokenizer(model=model, custom_tokenizer=custom_tokenizer)
    if tokenizer is not None:
        try:
            return max(1, len(tokenizer.encode(payload)))
        except Exception:
            logger.debug('Tokenizer encode failed; falling back to heuristic.')

    # Heuristic fallback:
    # - 4.2 chars/token is closer than 4.0 for English/code heavy prompts
    # - include a small per-message overhead to account for chat wrappers
    base = len(payload) / 4.2
    overhead = len(messages) * 3
    return max(1, int(base + overhead))


def _messages_to_token_payload(messages: list[dict] | list[Message]) -> str:
    parts: list[str] = []
    for m in messages:
        if isinstance(m, dict):
            role = str(m.get('role', ''))
            name = str(m.get('name', ''))
            content = m.get('content', '')
            tool_calls = m.get('tool_calls')
        else:
            role = str(getattr(m, 'role', ''))
            name = str(getattr(m, 'name', ''))
            content = getattr(m, 'content', '')
            tool_calls = getattr(m, 'tool_calls', None)

        if role:
            parts.append(f'role:{role}')
        if name:
            parts.append(f'name:{name}')
        parts.append(_content_to_text(content))
        parts.append(_tool_calls_to_text(tool_calls))

    return '\n'.join(p for p in parts if p)


def _content_to_text(content: Any) -> str:
    if isinstance(content, list):
        text_parts: list[str] = []
        for part in content:
            if isinstance(part, dict):
                text = part.get('text')
                if text:
                    text_parts.append(str(text))
                elif part:
                    text_parts.append(str(part))
            else:
                text = getattr(part, 'text', None)
                if text:
                    text_parts.append(str(text))
                elif part is not None:
                    text_parts.append(str(part))
        return '\n'.join(text_parts)
    if content is None:
        return ''
    return str(content)


def _tool_calls_to_text(tool_calls: Any) -> str:
    if not isinstance(tool_calls, list):
        return ''
    serialized: list[str] = []
    for call in tool_calls:
        if not isinstance(call, dict):
            serialized.append(str(call))
            continue
        fn = call.get('function')
        if isinstance(fn, dict):
            name = str(fn.get('name', ''))
            args = str(fn.get('arguments', ''))
            serialized.append(f'tool:{name} args:{args}')
        else:
            serialized.append(str(call))
    return '\n'.join(serialized)


def _resolve_tokenizer(model: str, custom_tokenizer: Any) -> Any:
    tokenizer = _normalize_custom_tokenizer(custom_tokenizer)
    if tokenizer is not None:
        return tokenizer
    return _get_tiktoken_for_model(model)


def _normalize_custom_tokenizer(custom_tokenizer: Any) -> Any:
    if custom_tokenizer is None:
        return None
    if hasattr(custom_tokenizer, 'encode') and callable(custom_tokenizer.encode):
        return custom_tokenizer
    if isinstance(custom_tokenizer, str):
        return create_pretrained_tokenizer(custom_tokenizer)
    return None


@lru_cache(maxsize=16)
def _get_tiktoken_for_model(model: str) -> Any:
    if not model:
        return None
    try:
        import tiktoken  # type: ignore

        try:
            return tiktoken.encoding_for_model(model)
        except Exception:
            return tiktoken.get_encoding('cl100k_base')
    except Exception:
        return None


def create_pretrained_tokenizer(name: str) -> Any:
    """Create tokenizer by name when available, else return name unchanged."""
    if not name:
        return name
    try:
        import tiktoken  # type: ignore

        try:
            return tiktoken.encoding_for_model(name)
        except Exception:
            return tiktoken.get_encoding(name)
    except Exception:
        return name
    return name
