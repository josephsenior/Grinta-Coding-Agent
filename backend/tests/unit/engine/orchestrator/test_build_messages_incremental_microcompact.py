"""Tests for incremental build_messages cache with microcompact."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from backend.context.compactor.microcompact import apply_microcompact
from backend.engine.memory_manager import ContextMemoryManager
from backend.ledger.action import CmdRunAction, MessageAction
from backend.ledger.event import EventSource
from backend.ledger.observation.commands import CmdOutputObservation


class _State:
    def __init__(self) -> None:
        self.extra_data: dict[str, object] = {}
        self.history: list = []

    def set_extra(self, key: str, value: object, *, source: str = '') -> None:
        self.extra_data[key] = value


def _build_cmd_obs_chain(count: int, *, start_id: int = 2) -> list:
    events = []
    event_id = start_id
    for idx in range(count):
        action = CmdRunAction(command=f'echo {idx}')
        action.id = event_id
        event_id += 1
        observation = CmdOutputObservation(
            content=f'payload {idx} ' * 80,
            command=f'echo {idx}',
        )
        observation.id = event_id
        event_id += 1
        events.extend([action, observation])
    return events


def test_build_messages_uses_incremental_append_after_microcompact_ages_event():
    manager = ContextMemoryManager(
        config=MagicMock(compactor_config=None),
        llm_registry=MagicMock(),
    )
    manager.conversation_memory = MagicMock()
    manager.conversation_memory.process_events.return_value = [MagicMock()]
    manager.conversation_memory.process_events_appending.return_value = [MagicMock()]

    initial_user = MessageAction(content='start')
    initial_user.source = EventSource.USER
    initial_user.id = 1

    state = _State()
    llm_config = SimpleNamespace(
        max_message_chars=None,
        vision_is_active=False,
        model='gpt-4o',
        caching_prompt=False,
        prompt_history_windowing_enabled=True,
        prompt_history_token_budget=None,
        prompt_history_max_events=None,
    )

    events = [initial_user, *_build_cmd_obs_chain(45, start_id=2)]
    state.history = list(events)

    manager._pipeline = MagicMock()
    manager._pipeline.build_prompt_events.side_effect = (
        lambda condensed, state=None, llm_config=None, full_history=None: (
            apply_microcompact(
                list(condensed),
                preserve_recent=10,
                state=state,
            )
        )
    )

    manager.build_messages(events, initial_user, llm_config, state=state)
    assert manager.conversation_memory.process_events.called
    assert not manager.conversation_memory.process_events_appending.called

    events.append(CmdRunAction(command='echo tail'))
    events[-1].id = 200
    events.append(
        CmdOutputObservation(content='tail payload ' * 40, command='echo tail')
    )
    events[-1].id = 201
    state.history = list(events)

    manager.build_messages(events, initial_user, llm_config, state=state)

    manager.conversation_memory.process_events_appending.assert_called_once()
    append_kwargs = (
        manager.conversation_memory.process_events_appending.call_args.kwargs
    )
    assert append_kwargs['prefix_event_count'] == len(events) - 2
