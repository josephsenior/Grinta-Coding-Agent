"""Helpers for preserving USER MessageActions in LLM-facing prompts."""

from __future__ import annotations

from collections.abc import Iterable
from typing import cast

from backend.context.prompt.prompt_window import event_fingerprint
from backend.ledger.action import MessageAction
from backend.ledger.event import Event, EventSource

PROTECTED_RECENT_USER_MESSAGE_COUNT = 6
DEFAULT_PROMPT_USER_TURN_LIMIT = 6


def is_nonempty_user_message(event: Event) -> bool:
    return (
        isinstance(event, MessageAction)
        and getattr(event, 'source', None) == EventSource.USER
        and bool(str(getattr(event, 'content', '') or '').strip())
    )


def collect_user_messages(
    events: Iterable[Event],
    *,
    max_turns: int | None = None,
) -> list[MessageAction]:
    """Return USER MessageActions in chronological order."""
    users = [event for event in events if is_nonempty_user_message(event)]
    if max_turns is not None and max_turns > 0 and len(users) > max_turns:
        return cast(list[MessageAction], users[-max_turns:])
    return cast(list[MessageAction], users)


def user_message_present(
    prompt_events: Iterable[Event], user_event: MessageAction
) -> bool:
    user_id = getattr(user_event, 'id', None)
    user_fp = event_fingerprint(user_event)
    for event in prompt_events:
        if not isinstance(event, MessageAction):
            continue
        if getattr(event, 'source', None) != EventSource.USER:
            continue
        if user_id is not None and getattr(event, 'id', None) == user_id:
            return True
        if event_fingerprint(event) == user_fp:
            return True
    return False


def merge_missing_user_turns(
    prompt_events: list[Event],
    full_history: list[Event],
    *,
    max_turns: int = DEFAULT_PROMPT_USER_TURN_LIMIT,
) -> list[Event]:
    """Insert recent USER turns from *full_history* missing from *prompt_events*."""
    if not full_history or not prompt_events:
        return prompt_events

    missing = [
        user
        for user in collect_user_messages(full_history, max_turns=max_turns)
        if not user_message_present(prompt_events, user)
    ]
    if not missing:
        return prompt_events

    history_index = {
        id(event): index
        for index, event in enumerate(full_history)
        if id(event) is not None
    }
    merged = list(prompt_events)
    for user in missing:
        user_pos = history_index.get(id(user))
        if user_pos is None:
            merged.append(user)
            continue
        insert_at = len(merged)
        for index, event in enumerate(merged):
            event_pos = history_index.get(id(event))
            if event_pos is not None and event_pos > user_pos:
                insert_at = index
                break
        merged.insert(insert_at, user)
    return merged


__all__ = [
    'DEFAULT_PROMPT_USER_TURN_LIMIT',
    'PROTECTED_RECENT_USER_MESSAGE_COUNT',
    'collect_user_messages',
    'is_nonempty_user_message',
    'merge_missing_user_turns',
    'user_message_present',
]
