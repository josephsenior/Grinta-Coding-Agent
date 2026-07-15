"""Tests for backend.engine.memory_manager."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from backend.engine.memory_manager import (
    CondensedHistory,
    ContextMemoryManager,
)
from backend.ledger.event import Event

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_config(compactor_config=None) -> MagicMock:
    cfg = MagicMock()
    cfg.compactor_config = compactor_config
    return cfg


def _make_llm_registry() -> MagicMock:
    return MagicMock()


def _make_manager(compactor_config=None) -> ContextMemoryManager:
    return ContextMemoryManager(
        config=_make_config(compactor_config=compactor_config),
        llm_registry=_make_llm_registry(),
    )


def _make_event(
    source_value, is_message_action=False, action_type=None, content='hello'
):
    """Build a minimal mock event."""
    event = MagicMock()
    event.source = source_value
    event.content = content
    event.action = action_type
    event.file_urls = None
    event.image_urls = None
    event.wait_for_response = False
    if is_message_action:
        from backend.ledger.action import MessageAction

        ma = MessageAction(
            content=content,
            file_urls=None,
            image_urls=None,
            wait_for_response=False,
        )
        ma.source = source_value
        return ma
    return event


# ---------------------------------------------------------------------------
# CondensedHistory dataclass
# ---------------------------------------------------------------------------


class TestCondensedHistory:
    def test_defaults_no_pending_action(self):
        ch = CondensedHistory(events=[], pending_action=None)
        assert ch.events == []
        assert ch.pending_action is None

    def test_with_events_and_action(self):
        events = [MagicMock(), MagicMock()]
        action = MagicMock()
        ch = CondensedHistory(events=cast(list[Event], events), pending_action=action)
        assert len(ch.events) == 2
        assert ch.pending_action is action

    def test_is_dataclass(self):
        import dataclasses

        assert dataclasses.is_dataclass(CondensedHistory)


# ---------------------------------------------------------------------------
# ContextMemoryManager.__init__
# ---------------------------------------------------------------------------


class TestContextMemoryManagerInit:
    def test_conversation_memory_none_initially(self):
        m = _make_manager()
        assert m.conversation_memory is None

    def test_pipeline_none_initially(self):
        m = _make_manager()
        assert m._pipeline is None

    def test_config_and_registry_stored(self):
        cfg = _make_config()
        reg = _make_llm_registry()
        m = ContextMemoryManager(config=cfg, llm_registry=reg)
        assert m._config is cfg
        assert m._llm_registry is reg


# ---------------------------------------------------------------------------
# should_emit_compaction_status
# ---------------------------------------------------------------------------


class TestShouldEmitCompactionStatus:
    def _make_state(self) -> MagicMock:
        state = MagicMock()
        state.history = []
        state.view = MagicMock(unhandled_condensation_request=False)
        state.turn_signals = MagicMock(
            prewarmed_compaction=None,
            memory_pressure=None,
        )
        return state

    def test_false_without_pipeline(self):
        m = _make_manager()
        assert m.should_emit_compaction_status(self._make_state()) is False

    def test_delegates_to_pipeline(self):
        m = _make_manager()
        pipeline = MagicMock(should_emit_compaction_status=MagicMock(return_value=True))
        m._pipeline = pipeline
        state = self._make_state()

        assert m.should_emit_compaction_status(state) is True
        pipeline.should_emit_compaction_status.assert_called_once_with(state)


# ---------------------------------------------------------------------------
# initialize
# ---------------------------------------------------------------------------


class TestInitialize:
    def test_initialize_creates_conversation_memory(self):
        m = _make_manager()
        pm = MagicMock()
        with patch('backend.engine.memory_manager.ContextMemory') as MockCM:
            MockCM.return_value = MagicMock(name='conv_mem')
            m.initialize(pm)
        assert m.conversation_memory is not None

    def test_initialize_creates_pipeline(self):
        m = _make_manager(compactor_config=MagicMock())
        pm = MagicMock()
        fake_pipeline = MagicMock()
        with (
            patch('backend.engine.memory_manager.ContextMemory'),
            patch(
                'backend.context.context_pipeline.ContextPipeline.from_config',
                return_value=fake_pipeline,
            ),
        ):
            m.initialize(pm)
        assert m._pipeline is fake_pipeline

    def test_initialize_context_pipeline_binds_registry_default_llm(self):
        from backend.core.config.agent_config import AgentConfig
        from backend.core.config.app_config import AppConfig
        from backend.core.config.compactor_config import ContextPipelineConfig
        from backend.core.config.llm_config import LLMConfig

        llm_config = LLMConfig.model_validate({'model': 'openai/gpt-4o'})
        app_config = AppConfig()
        app_config.set_llm_config(llm_config)
        agent_config = AgentConfig(compactor_config=ContextPipelineConfig())
        registry = MagicMock()
        registry.config = app_config
        manager = ContextMemoryManager(config=agent_config, llm_registry=registry)

        with (
            patch('backend.engine.memory_manager.ContextMemory'),
            patch(
                'backend.context.context_pipeline.ContextPipeline.from_config'
            ) as mock_from_config,
        ):
            mock_from_config.return_value = MagicMock()
            manager.initialize(MagicMock())

        bound_config = mock_from_config.call_args.args[0]
        assert bound_config.llm_config is llm_config

    def test_pipeline_compaction_always_uses_agent_model_config(self):
        from backend.core.config.compactor_config import ContextPipelineConfig
        from backend.core.config.llm_config import LLMConfig

        agent_llm = LLMConfig.model_validate({'model': 'openai/agent-model'})
        other_llm = LLMConfig.model_validate({'model': 'openai/other-model'})
        config = MagicMock()
        config.compactor_config = ContextPipelineConfig(llm_config=other_llm)
        config.get_llm_config.return_value = agent_llm
        manager = ContextMemoryManager(config=config, llm_registry=MagicMock())

        normalized = manager._normalized_pipeline_config()

        assert normalized.llm_config is agent_llm


# ---------------------------------------------------------------------------
# condense_history
# ---------------------------------------------------------------------------


class TestCondenseHistory:
    def _make_state_with_history(self, events=None) -> MagicMock:
        state = MagicMock()
        state.history = events or []
        state.extra_data = {}
        turn_signals = MagicMock(memory_pressure=None)
        turn_signals.prewarmed_compaction = None
        state.turn_signals = turn_signals
        state.ack_memory_pressure = MagicMock()
        state.view = MagicMock(unhandled_condensation_request=False)
        return state

    async def test_no_pipeline_returns_all_history(self):
        m = _make_manager()
        events = [MagicMock(), MagicMock()]
        state = self._make_state_with_history(events)
        result = await m.condense_history(state)
        assert isinstance(result, CondensedHistory)
        assert result.events == events
        assert result.pending_action is None

    async def test_delegates_to_pipeline(self):
        m = _make_manager()
        expected = CondensedHistory(events=[MagicMock()], pending_action=None)
        pipeline = MagicMock(prepare_step=AsyncMock(return_value=expected))
        m._pipeline = pipeline
        state = self._make_state_with_history()

        result = await m.condense_history(state)

        pipeline.prepare_step.assert_awaited_once()
        assert result is expected


# ---------------------------------------------------------------------------
# get_initial_user_message
# ---------------------------------------------------------------------------


class TestGetInitialUserMessage:
    def test_finds_message_action_from_user(self):
        from backend.ledger.action import MessageAction
        from backend.ledger.event import EventSource

        msg = MessageAction(
            content='hi', file_urls=None, image_urls=None, wait_for_response=False
        )
        msg.source = EventSource.USER

        m = _make_manager()
        result = m.get_initial_user_message([msg])
        assert result is msg

    def test_skips_non_user_events(self):
        from backend.ledger.action import MessageAction
        from backend.ledger.event import EventSource

        agent_event = MagicMock()
        agent_event.source = EventSource.AGENT

        user_msg = MessageAction(
            content='real', file_urls=None, image_urls=None, wait_for_response=False
        )
        user_msg.source = EventSource.USER

        m = _make_manager()
        result = m.get_initial_user_message([agent_event, user_msg])
        assert result is user_msg

    def test_raises_value_error_when_no_user_message(self):
        from backend.ledger.event import EventSource

        agent_event = MagicMock()
        agent_event.source = EventSource.AGENT

        m = _make_manager()
        with pytest.raises(ValueError, match='Initial user message not found'):
            m.get_initial_user_message([agent_event])

    def test_raises_value_error_on_empty_iterable(self):
        m = _make_manager()
        with pytest.raises(ValueError, match='Initial user message not found'):
            m.get_initial_user_message([])

    def test_returns_first_user_message_when_multiple(self):
        from backend.ledger.action import MessageAction
        from backend.ledger.event import EventSource

        first = MessageAction(
            content='first', file_urls=None, image_urls=None, wait_for_response=False
        )
        first.source = EventSource.USER
        second = MessageAction(
            content='second', file_urls=None, image_urls=None, wait_for_response=False
        )
        second.source = EventSource.USER

        m = _make_manager()
        result = m.get_initial_user_message([first, second])
        assert result.content == 'first'

    def test_tolerates_exception_in_individual_event(self):
        from backend.ledger.action import MessageAction
        from backend.ledger.event import EventSource

        # An event whose .source property raises
        bad_event = MagicMock()
        bad_event.source = PropertyMock(side_effect=Exception('oops'))
        type(bad_event).source = PropertyMock(side_effect=Exception('oops'))

        good_event = MessageAction(
            content='ok', file_urls=None, image_urls=None, wait_for_response=False
        )
        good_event.source = EventSource.USER

        m = _make_manager()
        result = m.get_initial_user_message([good_event])
        assert result.content == 'ok'

    def test_clones_non_message_action_user_event(self):
        """Events with ActionType.MESSAGE that are NOT MessageAction are cloned.

        We use a real subclass to ensure isinstance(event, MessageAction) is False
        while still having .action == ActionType.MESSAGE.
        """
        from backend.core.schemas import ActionType
        from backend.ledger.action import MessageAction
        from backend.ledger.event import EventSource

        class _RawEvent:
            """Minimal non-MessageAction event that looks like a MESSAGE action."""

            source = EventSource.USER
            action = ActionType.MESSAGE
            content = 'cloned content'
            file_urls = None
            image_urls = None
            wait_for_response = False

        m = _make_manager()
        result = m.get_initial_user_message([cast(Event, _RawEvent())])
        assert isinstance(result, MessageAction)
        assert result.content == 'cloned content'


# ---------------------------------------------------------------------------
# build_messages
# ---------------------------------------------------------------------------


class TestBuildMessages:
    @staticmethod
    def _attach_pipeline(m: ContextMemoryManager, *, window: int | None = None) -> None:
        pipeline = MagicMock()

        def _build_prompt_events(condensed, **kwargs):
            events = list(condensed)
            if window is not None and len(events) > window:
                return events[-window:]
            return events

        pipeline.build_prompt_events = MagicMock(side_effect=_build_prompt_events)
        m._pipeline = pipeline

    def test_raises_runtime_error_if_not_initialized(self):
        m = _make_manager()
        with pytest.raises(RuntimeError, match='not initialized'):
            m.build_messages([], MagicMock(), MagicMock())

    def test_reuses_pipeline_prompt_window_accounting(self):
        from backend.context.prompt.prompt_window import PromptWindowResult

        m = _make_manager()
        event = MagicMock()
        window = PromptWindowResult(
            events=[event],
            original_events=1,
            selected_events=1,
            dropped_events=0,
            estimated_tokens=17,
            selected_estimated_tokens=17,
            token_budget=100,
            protected_events=0,
            windowed=False,
            reason='within_budget',
            cache_fingerprint='abc',
        )
        pipeline = MagicMock()
        pipeline.build_prompt_window.return_value = window
        m._pipeline = pipeline

        events, resolved = m._resolve_prompt_events([], None, MagicMock())

        assert events == [event]
        assert resolved is window
        pipeline.build_prompt_events.assert_not_called()

    def test_returns_empty_list_when_process_events_returns_empty(self):
        m = _make_manager()
        self._attach_pipeline(m)
        m.conversation_memory = MagicMock()
        m.conversation_memory.process_events.return_value = []

        result = m.build_messages([], MagicMock(), MagicMock())
        assert result == []

    def test_windows_events_before_processing(self):
        from backend.ledger.action import CmdRunAction, MessageAction
        from backend.ledger.event import EventSource
        from backend.ledger.observation import CmdOutputObservation

        m = _make_manager()
        self._attach_pipeline(m, window=8)
        m.conversation_memory = MagicMock()
        m.conversation_memory.process_events.return_value = []
        initial_user = MessageAction(content='start')
        initial_user.source = EventSource.USER
        initial_user.id = 1
        events: list[Event] = [initial_user]
        event_id = 2
        for idx in range(20):
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
        llm_config = SimpleNamespace(
            max_message_chars=None,
            vision_is_active=False,
            model='gpt-4o',
            caching_prompt=False,
            prompt_history_token_budget=120,
            prompt_history_min_events=1,
            prompt_history_max_events=8,
        )

        m.build_messages(events, initial_user, llm_config)

        processed_events = m.conversation_memory.process_events.call_args.kwargs[
            'condensed_history'
        ]
        assert len(processed_events) < len(events)
        assert events[-2] in processed_events

    def test_sets_cache_prompt_on_first_text_content(self):
        from backend.core.message import Message, TextContent

        m = _make_manager()
        self._attach_pipeline(m)
        tc = TextContent(text='system prompt')
        msg = Message(role='system', content=[tc])
        m.conversation_memory = MagicMock()
        m.conversation_memory.process_events.return_value = [msg]

        llm_config = MagicMock()
        llm_config.max_message_chars = None
        llm_config.vision_is_active = False
        llm_config.model = 'claude-sonnet-4-6'
        llm_config.caching_prompt = True

        messages = m.build_messages([], MagicMock(), llm_config)
        assert tc.cache_prompt is True
        assert messages[0].cache_enabled is True

    def test_sets_cache_prompt_on_last_user_message(self):
        from backend.core.message import Message, TextContent

        m = _make_manager()
        self._attach_pipeline(m)
        system_tc = TextContent(text='sys')
        user_tc = TextContent(text='user msg')
        sys_msg = Message(role='system', content=[system_tc])
        user_msg = Message(role='user', content=[user_tc])
        m.conversation_memory = MagicMock()
        m.conversation_memory.process_events.return_value = [sys_msg, user_msg]

        llm_config = MagicMock()
        llm_config.max_message_chars = None
        llm_config.vision_is_active = False
        llm_config.model = 'anthropic/claude-sonnet-4-6'
        llm_config.caching_prompt = True

        messages = m.build_messages([], MagicMock(), llm_config)
        assert user_tc.cache_prompt is True
        assert messages[-1].cache_enabled is True

    def test_does_not_set_cache_prompt_for_openai_model(self):
        from backend.core.message import Message, TextContent

        m = _make_manager()
        self._attach_pipeline(m)
        system_tc = TextContent(text='sys')
        user_tc = TextContent(text='user msg')
        sys_msg = Message(role='system', content=[system_tc])
        user_msg = Message(role='user', content=[user_tc])
        m.conversation_memory = MagicMock()
        m.conversation_memory.process_events.return_value = [sys_msg, user_msg]

        llm_config = MagicMock()
        llm_config.max_message_chars = None
        llm_config.vision_is_active = False
        llm_config.model = 'gpt-4o'
        llm_config.caching_prompt = True

        m.build_messages([], MagicMock(), llm_config)
        assert system_tc.cache_prompt is False
        assert user_tc.cache_prompt is False

    def test_does_not_set_cache_prompt_when_caching_disabled(self):
        from backend.core.message import Message, TextContent

        m = _make_manager()
        self._attach_pipeline(m)
        tc = TextContent(text='system prompt')
        msg = Message(role='system', content=[tc])
        m.conversation_memory = MagicMock()
        m.conversation_memory.process_events.return_value = [msg]

        llm_config = MagicMock()
        llm_config.max_message_chars = None
        llm_config.vision_is_active = False
        llm_config.model = 'claude-sonnet-4-6'
        llm_config.caching_prompt = False

        m.build_messages([], MagicMock(), llm_config)
        assert tc.cache_prompt is False
