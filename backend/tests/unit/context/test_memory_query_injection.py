"""Tests for task-scoped workspace memory query wiring."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.context.conversation_memory import ContextMemory
from backend.ledger.action import MessageAction
from backend.ledger.event import EventSource


def _make_memory() -> ContextMemory:
    prompt_manager = MagicMock()
    config = MagicMock()
    return ContextMemory(config, prompt_manager)


def test_ensure_system_message_passes_first_user_message_as_memory_query() -> None:
    memory = _make_memory()
    initial = MessageAction(content='debug authentication middleware failures')
    initial.source = EventSource.USER
    events: list = []

    memory._ensure_system_message(events, initial_user_action=initial)

    memory.prompt_manager.get_system_message.assert_called_once()
    kwargs = memory.prompt_manager.get_system_message.call_args.kwargs
    assert kwargs['memory_query'] == 'debug authentication middleware failures'


def test_memory_query_for_prompt_prefers_initial_user_action() -> None:
    memory = _make_memory()
    initial = MessageAction(content='first task')
    initial.source = EventSource.USER
    later = MessageAction(content='follow-up question')
    later.source = EventSource.USER

    query = memory._memory_query_for_prompt(
        events=[later],
        initial_user_action=initial,
    )
    assert query == 'first task'
