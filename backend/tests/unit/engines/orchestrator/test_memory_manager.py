"""Tests for backend.engines.orchestrator.memory_manager."""
from __future__ import annotations

from unittest.mock import MagicMock, patch, PropertyMock
from typing import Any, cast

import pytest

from backend.engines.orchestrator.memory_manager import (
    CondensedHistory,
    ConversationMemoryManager,
)
from backend.events.event import Event


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_config(condenser_config=None) -> MagicMock:
    cfg = MagicMock()
    cfg.condenser_config = condenser_config
    return cfg


def _make_llm_registry() -> MagicMock:
    return MagicMock()


def _make_manager(condenser_config=None) -> ConversationMemoryManager:
    return ConversationMemoryManager(
        config=_make_config(condenser_config=condenser_config),
        llm_registry=_make_llm_registry(),
    )


def _make_event(source_value, is_message_action=False, action_type=None, content="hello"):
    """Build a minimal mock event."""

    event = MagicMock()
    event.source = source_value
    event.content = content
    event.action = action_type
    event.file_urls = None
    event.image_urls = None
    event.wait_for_response = False
    if is_message_action:
        from backend.events.action import MessageAction
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
# ConversationMemoryManager.__init__
# ---------------------------------------------------------------------------

class TestConversationMemoryManagerInit:
    def test_conversation_memory_none_initially(self):
        m = _make_manager()
        assert m.conversation_memory is None

    def test_condenser_none_initially(self):
        m = _make_manager()
        assert m.condenser is None

    def test_config_and_registry_stored(self):
        cfg = _make_config()
        reg = _make_llm_registry()
        m = ConversationMemoryManager(config=cfg, llm_registry=reg)
        assert m._config is cfg
        assert m._llm_registry is reg


# ---------------------------------------------------------------------------
# initialize and _init_condenser
# ---------------------------------------------------------------------------

class TestInitialize:
    def test_initialize_creates_conversation_memory(self):
        m = _make_manager()
        pm = MagicMock()
        with patch("backend.engines.orchestrator.memory_manager.ConversationMemory") as MockCM:
            MockCM.return_value = MagicMock(name="conv_mem")
            m.initialize(pm)
        assert m.conversation_memory is not None

    def test_initialize_no_condenser_config_leaves_condenser_none(self):
        m = _make_manager(condenser_config=None)
        pm = MagicMock()
        with patch("backend.engines.orchestrator.memory_manager.ConversationMemory"):
            m.initialize(pm)
        assert m.condenser is None

    def test_initialize_with_condenser_config_creates_condenser(self):
        condenser_config = MagicMock()
        m = _make_manager(condenser_config=condenser_config)
        pm = MagicMock()
        fake_condenser = MagicMock()
        with (
            patch("backend.engines.orchestrator.memory_manager.ConversationMemory"),
            patch("backend.engines.orchestrator.memory_manager.Condenser") as MockCondenser,
        ):
            MockCondenser.from_config.return_value = fake_condenser
            m.initialize(pm)
        assert m.condenser is fake_condenser


# ---------------------------------------------------------------------------
# condense_history
# ---------------------------------------------------------------------------

class TestCondenseHistory:
    def _make_state_with_history(self, events=None) -> MagicMock:
        state = MagicMock()
        state.history = events or []
        state.extra_data = {}
        return state

    def test_no_condenser_returns_all_history(self):
        m = _make_manager()
        events = [MagicMock(), MagicMock()]
        state = self._make_state_with_history(events)
        result = m.condense_history(state)
        assert isinstance(result, CondensedHistory)
        assert result.events == events
        assert result.pending_action is None

    def test_condenser_view_result_returns_view_events(self):
        m = _make_manager()
        from backend.memory.view import View

        mock_condenser = MagicMock()
        view = MagicMock(spec=View)
        view.events = cast(list[Event], [MagicMock(), MagicMock()])
        mock_condenser.condensed_history.return_value = view
        m.condenser = mock_condenser

        state = self._make_state_with_history()
        result = m.condense_history(state)
        assert result.events == view.events
        assert result.pending_action is None

    def test_condenser_non_view_result_returns_action(self):
        m = _make_manager()

        mock_condenser = MagicMock()
        condensation = MagicMock()
        # Not a View instance → will reach the else branch
        cast(Any, condensation).__class__ = object  # NOT a View
        condensation.action = MagicMock(name="action")
        mock_condenser.condensed_history.return_value = condensation
        m.condenser = mock_condenser

        state = self._make_state_with_history()
        result = m.condense_history(state)
        assert result.events == []
        assert result.pending_action is condensation.action

    def test_memory_pressure_not_set_skips_forced_condensation(self):
        m = _make_manager()
        from backend.memory.view import View

        mock_condenser = MagicMock()
        view = MagicMock(spec=View)
        view.events = []
        mock_condenser.condensed_history.return_value = view
        m.condenser = mock_condenser

        state = self._make_state_with_history()
        state.extra_data = {}  # no memory_pressure key
        result = m.condense_history(state)
        assert isinstance(result, CondensedHistory)


# ---------------------------------------------------------------------------
# get_initial_user_message
# ---------------------------------------------------------------------------

class TestGetInitialUserMessage:
    def test_finds_message_action_from_user(self):
        from backend.events.action import MessageAction
        from backend.events.event import EventSource

        msg = MessageAction(content="hi", file_urls=None, image_urls=None, wait_for_response=False)
        msg.source = EventSource.USER

        m = _make_manager()
        result = m.get_initial_user_message([msg])
        assert result is msg

    def test_skips_non_user_events(self):
        from backend.events.action import MessageAction
        from backend.events.event import EventSource

        agent_event = MagicMock()
        agent_event.source = EventSource.AGENT

        user_msg = MessageAction(content="real", file_urls=None, image_urls=None, wait_for_response=False)
        user_msg.source = EventSource.USER

        m = _make_manager()
        result = m.get_initial_user_message([agent_event, user_msg])
        assert result is user_msg

    def test_raises_value_error_when_no_user_message(self):
        from backend.events.event import EventSource

        agent_event = MagicMock()
        agent_event.source = EventSource.AGENT

        m = _make_manager()
        with pytest.raises(ValueError, match="Initial user message not found"):
            m.get_initial_user_message([agent_event])

    def test_raises_value_error_on_empty_iterable(self):
        m = _make_manager()
        with pytest.raises(ValueError, match="Initial user message not found"):
            m.get_initial_user_message([])

    def test_returns_first_user_message_when_multiple(self):
        from backend.events.action import MessageAction
        from backend.events.event import EventSource

        first = MessageAction(content="first", file_urls=None, image_urls=None, wait_for_response=False)
        first.source = EventSource.USER
        second = MessageAction(content="second", file_urls=None, image_urls=None, wait_for_response=False)
        second.source = EventSource.USER

        m = _make_manager()
        result = m.get_initial_user_message([first, second])
        assert result.content == "first"

    def test_tolerates_exception_in_individual_event(self):
        from backend.events.action import MessageAction
        from backend.events.event import EventSource

        # An event whose .source property raises
        bad_event = MagicMock()
        bad_event.source = PropertyMock(side_effect=Exception("oops"))
        type(bad_event).source = PropertyMock(side_effect=Exception("oops"))

        good_event = MessageAction(content="ok", file_urls=None, image_urls=None, wait_for_response=False)
        good_event.source = EventSource.USER

        m = _make_manager()
        result = m.get_initial_user_message([good_event])
        assert result.content == "ok"

    def test_clones_non_message_action_user_event(self):
        """Events with ActionType.MESSAGE that are NOT MessageAction are cloned.

        We use a real subclass to ensure isinstance(event, MessageAction) is False
        while still having .action == ActionType.MESSAGE.
        """
        from backend.core.schemas import ActionType
        from backend.events.action import MessageAction
        from backend.events.event import EventSource

        class _RawEvent:
            """Minimal non-MessageAction event that looks like a MESSAGE action."""
            source = EventSource.USER
            action = ActionType.MESSAGE
            content = "cloned content"
            file_urls = None
            image_urls = None
            wait_for_response = False

        m = _make_manager()
        result = m.get_initial_user_message([cast(Event, _RawEvent())])
        assert isinstance(result, MessageAction)
        assert result.content == "cloned content"


# ---------------------------------------------------------------------------
# build_messages
# ---------------------------------------------------------------------------

class TestBuildMessages:
    def test_raises_runtime_error_if_not_initialized(self):
        m = _make_manager()
        with pytest.raises(RuntimeError, match="not initialized"):
            m.build_messages([], MagicMock(), MagicMock())

    def test_returns_empty_list_when_process_events_returns_empty(self):
        m = _make_manager()
        m.conversation_memory = MagicMock()
        m.conversation_memory.process_events.return_value = []

        result = m.build_messages([], MagicMock(), MagicMock())
        assert result == []

    def test_sets_cache_prompt_on_first_text_content(self):
        from backend.core.message import Message, TextContent

        m = _make_manager()
        tc = TextContent(text="system prompt")
        msg = Message(role="system", content=[tc])
        m.conversation_memory = MagicMock()
        m.conversation_memory.process_events.return_value = [msg]

        llm_config = MagicMock()
        llm_config.max_message_chars = None
        llm_config.vision_is_active = False
        llm_config.model = "claude-4-sonnet"
        llm_config.caching_prompt = True

        m.build_messages([], MagicMock(), llm_config)
        assert tc.cache_prompt is True

    def test_sets_cache_prompt_on_last_user_message(self):
        from backend.core.message import Message, TextContent

        m = _make_manager()
        system_tc = TextContent(text="sys")
        user_tc = TextContent(text="user msg")
        sys_msg = Message(role="system", content=[system_tc])
        user_msg = Message(role="user", content=[user_tc])
        m.conversation_memory = MagicMock()
        m.conversation_memory.process_events.return_value = [sys_msg, user_msg]

        llm_config = MagicMock()
        llm_config.max_message_chars = None
        llm_config.vision_is_active = False
        llm_config.model = "anthropic/claude-4-sonnet"
        llm_config.caching_prompt = True

        m.build_messages([], MagicMock(), llm_config)
        assert user_tc.cache_prompt is True

    def test_does_not_set_cache_prompt_for_openai_model(self):
        from backend.core.message import Message, TextContent

        m = _make_manager()
        system_tc = TextContent(text="sys")
        user_tc = TextContent(text="user msg")
        sys_msg = Message(role="system", content=[system_tc])
        user_msg = Message(role="user", content=[user_tc])
        m.conversation_memory = MagicMock()
        m.conversation_memory.process_events.return_value = [sys_msg, user_msg]

        llm_config = MagicMock()
        llm_config.max_message_chars = None
        llm_config.vision_is_active = False
        llm_config.model = "gpt-4o"
        llm_config.caching_prompt = True

        m.build_messages([], MagicMock(), llm_config)
        assert system_tc.cache_prompt is False
        assert user_tc.cache_prompt is False

    def test_does_not_set_cache_prompt_when_caching_disabled(self):
        from backend.core.message import Message, TextContent

        m = _make_manager()
        tc = TextContent(text="system prompt")
        msg = Message(role="system", content=[tc])
        m.conversation_memory = MagicMock()
        m.conversation_memory.process_events.return_value = [msg]

        llm_config = MagicMock()
        llm_config.max_message_chars = None
        llm_config.vision_is_active = False
        llm_config.model = "claude-4-sonnet"
        llm_config.caching_prompt = False

        m.build_messages([], MagicMock(), llm_config)
        assert tc.cache_prompt is False
