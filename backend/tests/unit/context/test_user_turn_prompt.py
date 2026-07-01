"""Tests for follow-up USER message visibility in LLM prompts."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.context.memory.conversation_memory import ContextMemory
from backend.context.prompt.user_turns import merge_missing_user_turns
from backend.core.message import TextContent
from backend.ledger.action import MessageAction
from backend.ledger.action.message import SystemMessageAction
from backend.ledger.event import EventSource
from backend.orchestration.services.event_router_service import EventRouterService


def _user(text: str, event_id: int) -> MessageAction:
    event = MessageAction(content=text)
    event.source = EventSource.USER
    event.id = event_id
    return event


def _system(text: str = 'You are Grinta.') -> SystemMessageAction:
    event = SystemMessageAction(content=text)
    event.id = 0
    return event


def _make_memory() -> ContextMemory:
    prompt_manager = MagicMock()
    prompt_manager.get_system_message.return_value = 'You are Grinta.'
    prompt_manager.get_mcp_user_addendum.return_value = ''
    config = MagicMock()
    config.enable_vector_memory = False
    config.enable_som_visual_browsing = False
    config.cli_mode = True
    config.enable_hybrid_retrieval = False
    return ContextMemory(config=config, prompt_manager=prompt_manager)


def _user_texts(messages) -> list[str]:
    return [
        item.text
        for message in messages
        if message.role == 'user'
        for item in message.content
        if isinstance(item, TextContent)
    ]


def test_process_events_includes_follow_up_user_turns() -> None:
    first = _user('Build LZW compressor', 1)
    follow_up = _user('Stop and answer in plain text', 2)
    steering = _user('What is the project status?', 3)
    events = [_system(), first, follow_up, steering]
    memory = _make_memory()

    messages = memory.process_events(events, first)

    assert len(_user_texts(messages)) == 3
    joined = '\n'.join(text.strip() for text in _user_texts(messages))
    assert 'Stop and answer in plain text' in joined
    assert 'What is the project status?' in joined


def test_ensure_initial_user_inserts_opener_without_dropping_follow_ups() -> None:
    first = _user('Original task', 1)
    follow_up = _user('New steering', 2)
    events = [_system(), follow_up]
    memory = _make_memory()

    memory._ensure_initial_user_message(events, first)

    assert events[1] is first
    assert follow_up in events
    messages = memory.process_events(events, first)
    assert len(_user_texts(messages)) == 2


def test_merge_missing_user_turns_restores_pruned_follow_up() -> None:
    first = _user('Original task', 1)
    follow_up = _user('Answer me now', 2)
    history = [_system(), first, follow_up]
    prompt_events = [_system(), first]

    merged = merge_missing_user_turns(prompt_events, history)

    assert follow_up in merged
    assert merged.index(first) < merged.index(follow_up)


def test_user_message_syncs_canonical_state_without_planning_directive() -> None:
    controller = MagicMock()
    controller.state = MagicMock()
    controller.state.history = [_user('first', 1), _user('steering', 2)]
    controller.state.extra_data = {}

    service = EventRouterService(controller)

    with (
        patch(
            'backend.context.canonical_state.reduce_events_into_state'
        ) as reduce_mock,
        patch(
            'backend.context.compactor.pre_condensation_snapshot.extract_snapshot',
            return_value={'user_messages': [{'text': 'steering'}]},
        ),
        patch(
            'backend.context.compactor.pre_condensation_snapshot.save_snapshot'
        ) as save_mock,
    ):
        service._sync_user_message_context()

    reduce_mock.assert_called_once()
    save_mock.assert_called_once()
    assert 'planning_directive' not in controller.state.extra_data
