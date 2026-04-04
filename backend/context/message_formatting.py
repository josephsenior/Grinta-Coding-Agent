"""Message formatting and type-check utilities for ContextMemory.

Extracted from :mod:`backend.context.conversation_memory` to keep module
sizes within the repository guideline (~400 LOC).
"""

from __future__ import annotations

import copy
from typing import Any, Literal, TypeGuard

from backend.core.message import Message, TextContent
from backend.ledger.action import Action, MessageAction
from backend.ledger.observation import Observation

# ---------------------------------------------------------------------------
# Duck-typed type checks (resilient to module reloads)
# ---------------------------------------------------------------------------


def class_name_in_mro(obj: Any, target_name: str | None) -> bool:
    """Check whether an object's class hierarchy contains the given name."""
    if not target_name or obj is None:
        return False
    cls = obj if isinstance(obj, type) else type(obj)
    for base in getattr(cls, '__mro__', ()):
        if base.__name__ == target_name:
            return True
    return False


def is_instance_of(obj: Any, cls: type[Any]) -> bool:
    """Safely evaluate isinstance across duplicated module loads."""
    if isinstance(obj, cls):
        return True
    return class_name_in_mro(obj, getattr(cls, '__name__', None))


def is_text_content(content_item: Any) -> TypeGuard[TextContent]:
    """Duck-typed check for text content objects across module reloads."""
    if isinstance(content_item, TextContent):
        return True
    return bool(
        getattr(content_item, 'type', None) == 'text' and hasattr(content_item, 'text')
    )


def is_action_event(event: Any) -> bool:
    """Duck-typed action detection resilient to module reloads."""
    return is_instance_of(event, Action)


def is_observation_event(event: Any) -> bool:
    """Duck-typed observation detection resilient to module reloads."""
    return is_instance_of(event, Observation)


def is_message_action(event: Any) -> bool:
    """Helper for duck-typed MessageAction detection."""
    return is_instance_of(event, MessageAction)


# ---------------------------------------------------------------------------
# Text extraction helpers
# ---------------------------------------------------------------------------


def extract_first_text(message: Message | None) -> str | None:
    """Extract the first textual content from a *message*."""
    if not message or not getattr(message, 'content', None):
        return None
    for item in message.content:
        if is_text_content(item):
            return getattr(item, 'text', None)
    return None


def message_with_text(
    role: Literal['user', 'system', 'assistant', 'tool'], text: str
) -> Message:
    """Create a single-text-content :class:`Message`."""
    return Message(role=role, content=[TextContent(text=text)])


# ---------------------------------------------------------------------------
# Message list formatting
# ---------------------------------------------------------------------------


def remove_duplicate_system_prompt_user(messages: list[Message]) -> list[Message]:
    """Drop leading user messages that duplicate the system prompt.

    Pytest can reload action modules when different suites run together, which
    occasionally causes a `SystemMessageAction` to be deserialized through
    the generic fallback path (treated as a user message). This normalization
    removes the redundant user entry while preserving the rest of the
    conversation.
    """
    if len(messages) < 2:
        return messages
    system_text = extract_first_text(messages[0])
    first_user_text = extract_first_text(messages[1])
    if (
        messages[0].role == 'system'
        and messages[1].role == 'user'
        and system_text
        and first_user_text
        and first_user_text.strip() == system_text.strip()
    ):
        return [messages[0]] + messages[2:]
    return messages


def apply_user_message_formatting(messages: list[Message]) -> list[Message]:
    r"""Add newline separators between consecutive user messages.

    Ensures proper readability when multiple user messages appear
    consecutively by adding ``\\n\\n`` prefixes.
    """
    formatted_messages: list[Message] = []
    prev_role = None
    for msg in messages:
        current_role = getattr(msg, 'role', None)
        new_msg = (
            msg.model_copy(deep=True)
            if hasattr(msg, 'model_copy')
            else copy.deepcopy(msg)
        )
        if current_role == 'user' and prev_role == 'user' and (new_msg.content):
            for content_item in new_msg.content:
                if is_text_content(content_item):
                    if not getattr(content_item, 'text', '').startswith('\n\n'):
                        content_item.text = '\n\n' + getattr(content_item, 'text', '')
                    break
        formatted_messages.append(new_msg)
        prev_role = current_role
    return formatted_messages


__all__ = [
    'apply_user_message_formatting',
    'class_name_in_mro',
    'extract_first_text',
    'is_action_event',
    'is_instance_of',
    'is_message_action',
    'is_observation_event',
    'is_text_content',
    'message_with_text',
    'remove_duplicate_system_prompt_user',
]
