"""Prompt-cache hint helpers for ContextMemoryManager."""

from __future__ import annotations

from backend.core.message import Message, TextContent
from backend.inference.caching.prompt_caching import (
    should_mark_messages_for_prompt_cache,
)

_STABLE_USER_CACHE_POSITIONS = (3, 7)


def _mark_message_text_cacheable(message: Message) -> None:
    for item in message.content:
        if isinstance(item, TextContent):
            item.cache_prompt = True
            message.cache_enabled = True
            return


def _mark_stable_user_cache_positions(messages: list[Message]) -> None:
    user_msg_idx = 0
    for msg in messages:
        if msg.role != 'user':
            continue
        if user_msg_idx in _STABLE_USER_CACHE_POSITIONS:
            _mark_message_text_cacheable(msg)
        user_msg_idx += 1
        if user_msg_idx > max(_STABLE_USER_CACHE_POSITIONS):
            break


def _mark_trailing_user_cache_position(messages: list[Message]) -> None:
    for message in reversed(messages):
        if message.role != 'user':
            continue
        _mark_message_text_cacheable(message)
        break


def apply_prompt_cache_hints(messages: list[Message], llm_config: object) -> None:
    model = getattr(llm_config, 'model', None) or ''
    provider = getattr(llm_config, 'custom_llm_provider', None)
    caching_on = bool(getattr(llm_config, 'caching_prompt', True))
    if not caching_on or not should_mark_messages_for_prompt_cache(
        str(model),
        provider=str(provider) if provider else None,
    ):
        return

    _mark_message_text_cacheable(messages[0])

    # Stable intermediate anchors: mark the 4th and 8th user messages
    # (0-indexed positions 3 and 7).  Because these are absolute positions
    # from the start of the list they do *not* shift as new messages are
    # appended, so the Anthropic prompt cache can reuse the prefix across
    # successive turns.
    _mark_stable_user_cache_positions(messages)
    _mark_trailing_user_cache_position(messages)
