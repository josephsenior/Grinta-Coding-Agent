"""Stateless helpers for tracking and filtering paired tool-call / tool-response messages.

All functions are pure — they receive data and return results without touching
any instance state.  Extracted from
:class:`~backend.context.conversation_memory.ContextMemory` to improve
modularity and testability.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.core.message import Message

if TYPE_CHECKING:
    from collections.abc import Generator

    from backend.context.conversation_memory import _ToolCallTracking


def flush_resolved_tool_calls(tool_state: _ToolCallTracking) -> list[Message]:
    """Release pending tool-call responses once all tool outputs arrive."""
    resolved_messages: list[Message] = []
    response_ids_to_remove: list[str] = []
    for response_id, pending_message in tool_state.pending_action_messages.items():
        assert pending_message.tool_calls is not None, (
            'Tool calls should NOT be None when function calling is enabled &'
            f' the message is considered pending tool call. Pending message: {pending_message}'
        )
        if all(
            tool_call.id in tool_state.tool_call_messages
            for tool_call in pending_message.tool_calls
        ):
            resolved_messages.append(pending_message)
            for tool_call in pending_message.tool_calls:
                resolved_messages.append(
                    tool_state.tool_call_messages.pop(tool_call.id)
                )
            response_ids_to_remove.append(response_id)
    for response_id in response_ids_to_remove:
        tool_state.pending_action_messages.pop(response_id)
    return resolved_messages


def filter_unmatched_tool_calls(
    messages: list[Message],
) -> Generator[Message, None, None]:
    """Yield messages whose tool-call IDs have matching responses (and vice-versa).

    Messages without tool-call involvement pass through unchanged.
    """
    tool_call_ids = collect_tool_call_ids(messages)
    tool_response_ids = collect_tool_response_ids(messages)

    for message in messages:
        if _should_include_message(message, tool_call_ids, tool_response_ids):
            yield _maybe_trim_tool_calls(message, tool_response_ids)


def collect_tool_call_ids(messages: list[Message]) -> set[str]:
    """Collect all tool call IDs from assistant messages."""
    return {
        tool_call.id
        for message in messages
        if message.tool_calls
        for tool_call in message.tool_calls
        if message.role == 'assistant' and tool_call.id
    }


def collect_tool_response_ids(messages: list[Message]) -> set[str]:
    """Collect all tool response IDs from tool messages."""
    return {
        message.tool_call_id
        for message in messages
        if message.role == 'tool' and message.tool_call_id
    }


def _should_include_message(
    message: Message,
    tool_call_ids: set[str],
    tool_response_ids: set[str],
) -> bool:
    """Determine if a message should be included in the filtered results."""
    if message.role == 'tool' and message.tool_call_id:
        return message.tool_call_id in tool_call_ids
    if message.role == 'assistant' and message.tool_calls:
        return _all_tool_calls_match(message, tool_response_ids)
    return True


def _maybe_trim_tool_calls(
    message: Message,
    tool_response_ids: set[str],
) -> Message:
    """Remove tool calls from message that lack corresponding responses."""
    if message.role != 'assistant' or not message.tool_calls:
        return message

    matched_calls = [
        call for call in message.tool_calls if call.id in tool_response_ids
    ]
    if len(matched_calls) == len(message.tool_calls):
        return message
    if not matched_calls:
        raise StopIteration  # Should not be yielded by caller

    new_message = message.model_copy(deep=True)
    new_message.tool_calls = matched_calls
    return new_message


def _all_tool_calls_match(
    message: Message,
    tool_response_ids: set[str],
) -> bool:
    """Check if all tool calls in a message have matching responses."""
    if not message.tool_calls:
        return True

    all_match = all(
        tool_call.id in tool_response_ids for tool_call in message.tool_calls
    )
    if all_match:
        return True

    return bool(
        [
            tool_call
            for tool_call in message.tool_calls
            if tool_call.id in tool_response_ids
        ]
    )
