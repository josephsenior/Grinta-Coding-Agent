"""Unit tests for backend.context.conversation_memory — event→message conversion."""

from __future__ import annotations

import json
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from backend.context.conversation_memory import ContextMemory
from backend.context.memory_types import DecisionType
from backend.context.message_formatting import (
    apply_user_message_formatting,
    class_name_in_mro,
    extract_first_text,
    is_text_content,
    message_with_text,
    remove_duplicate_system_prompt_user,
)
from backend.core.message import Message, TextContent
from backend.integrations.mcp.mcp_utils import call_tool_mcp
from backend.ledger.action import MessageAction
from backend.ledger.action.mcp import MCPAction
from backend.ledger.event import EventSource
from backend.ledger.observation import AgentThinkObservation, ErrorObservation
from backend.ledger.observation.commands import CmdOutputObservation
from backend.ledger.observation.mcp import MCPObservation
from backend.ledger.tool import ToolCallMetadata

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**overrides):
    """Create a minimal AgentConfig-like object."""
    cfg = MagicMock()
    cfg.enable_vector_memory = False
    cfg.enable_som_visual_browsing = False
    cfg.cli_mode = True
    cfg.enable_hybrid_retrieval = False
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def _make_prompt_manager():
    pm = MagicMock()
    pm.get_system_message.return_value = 'You are App agent.'
    return pm


def _make_memory(**config_overrides) -> ContextMemory:
    return ContextMemory(
        config=_make_config(**config_overrides),
        prompt_manager=_make_prompt_manager(),
    )


def _text_msg(role: str, text: str) -> Message:
    return Message(role=role, content=[TextContent(text=text)])


# ---------------------------------------------------------------------------
# Static helpers
# ---------------------------------------------------------------------------


class TestErrorObservationNotifyUiOnly:
    def test_notify_ui_only_skips_llm_message(self):
        mem = _make_memory()
        obs = ErrorObservation(
            content='Authentication Error\n\ndetails',
            notify_ui_only=True,
        )
        out = mem._process_observation(
            obs,
            tool_call_id_to_message={},
            max_message_chars=None,
        )
        assert not out

    def test_default_error_still_converted_for_llm(self):
        mem = _make_memory()
        obs = ErrorObservation(content='MCP server unreachable')
        out = mem._process_observation(
            obs,
            tool_call_id_to_message={},
            max_message_chars=None,
        )
        assert len(out) == 1
        assert out[0].role == 'user'


class TestToolResultPropagation:
    def test_tool_result_ok_is_propagated_to_tool_ok(self):
        mem = _make_memory()
        obs = MCPObservation(
            content='{"ok": true}', name='remote_tool', arguments={'x': 1}
        )
        obs.tool_result = {'ok': True, 'retryable': False}
        obs.tool_call_metadata = ToolCallMetadata(
            function_name='remote_tool',
            tool_call_id='call_1',
            model_response={'id': 'resp_1'},
            total_calls_in_response=1,
        )
        tool_messages: dict[str, Message] = {}

        out = mem._process_observation(
            obs,
            tool_call_id_to_message=tool_messages,
            max_message_chars=None,
        )

        assert not out
        assert tool_messages['call_1'].tool_ok is True

    def test_tool_result_failure_is_propagated_to_tool_ok(self):
        mem = _make_memory()
        obs = MCPObservation(content='{"ok": false}', name='remote_tool', arguments={})
        obs.tool_result = {'ok': False, 'retryable': True, 'error_code': 'TIMEOUT'}
        obs.tool_call_metadata = ToolCallMetadata(
            function_name='remote_tool',
            tool_call_id='call_2',
            model_response={'id': 'resp_2'},
            total_calls_in_response=1,
        )
        tool_messages: dict[str, Message] = {}

        out = mem._process_observation(
            obs,
            tool_call_id_to_message=tool_messages,
            max_message_chars=None,
        )

        assert not out
        assert tool_messages['call_2'].tool_ok is False

    def test_cmd_output_exit_code_zero_propagates_success(self):
        mem = _make_memory()
        obs = CmdOutputObservation(
            content='tests passed',
            command='pytest',
            metadata={'exit_code': 0},
        )
        obs.tool_call_metadata = ToolCallMetadata(
            function_name='cmd_run',
            tool_call_id='call_3',
            model_response={'id': 'resp_3'},
            total_calls_in_response=1,
        )
        tool_messages: dict[str, Message] = {}

        out = mem._process_observation(
            obs,
            tool_call_id_to_message=tool_messages,
            max_message_chars=None,
        )

        assert not out
        assert tool_messages['call_3'].tool_ok is True

    @pytest.mark.asyncio
    async def test_mcp_failure_envelope_reaches_tool_message_cleanly(self):
        mem = _make_memory()
        action = MCPAction(name='remote_tool', arguments={'query': 'x'})

        obs = await call_tool_mcp([], action)
        assert isinstance(obs, MCPObservation)
        obs.tool_call_metadata = ToolCallMetadata(
            function_name='remote_tool',
            tool_call_id='call_4',
            model_response={'id': 'resp_4'},
            total_calls_in_response=1,
        )

        tool_messages: dict[str, Message] = {}
        out = mem._process_observation(
            obs,
            tool_call_id_to_message=tool_messages,
            max_message_chars=None,
        )

        assert not out
        assert tool_messages['call_4'].tool_ok is False
        payload = json.loads(obs.content)
        assert payload['error_code'] == 'MCP_NO_CLIENTS'
        assert payload['retryable'] is True
        assert payload['ok'] is False

    def test_agent_think_tool_result_uses_structured_tool_message_content(self):
        mem = _make_memory()
        obs = AgentThinkObservation(content='Your thought has been logged.')
        obs.tool_result = {
            'tool': 'checkpoint',
            'ok': True,
            'status': 'saved',
            'next_best_action': 'Continue with the next step.',
        }
        obs.tool_call_metadata = ToolCallMetadata(
            function_name='checkpoint',
            tool_call_id='call_5',
            model_response={'id': 'resp_5'},
            total_calls_in_response=1,
        )
        tool_messages: dict[str, Message] = {}

        out = mem._process_observation(
            obs,
            tool_call_id_to_message=tool_messages,
            max_message_chars=None,
        )

        assert not out
        assert json.loads(tool_messages['call_5'].content[0].text) == obs.tool_result  # type: ignore


class TestStaticHelpers:
    def test_message_with_text(self):
        msg = message_with_text('user', 'hello')
        assert msg.role == 'user'
        assert len(msg.content) == 1
        c = msg.content[0]
        assert isinstance(c, TextContent) and c.text == 'hello'

    def test_is_valid_image_url_valid(self):
        assert ContextMemory._is_valid_image_url('https://example.com/img.png') is True

    def test_is_valid_image_url_none(self):
        assert ContextMemory._is_valid_image_url(None) is False

    def test_is_valid_image_url_empty(self):
        assert ContextMemory._is_valid_image_url('') is False

    def test_is_valid_image_url_whitespace(self):
        assert ContextMemory._is_valid_image_url('   ') is False


class TestVectorMemoryInit:
    def test_enable_vector_memory_does_not_crash_and_sets_store(self, monkeypatch):
        from unittest.mock import MagicMock

        # Patch EnhancedVectorStore constructor to avoid optional deps.
        import backend.context.conversation_memory as cm

        fake_store = MagicMock(name='vector_store')
        monkeypatch.setattr(
            cm, 'EnhancedVectorStore', MagicMock(return_value=fake_store)
        )

        mem = _make_memory(enable_vector_memory=True)
        assert mem.vector_store is fake_store

    def test_is_text_content_true(self):
        tc = TextContent(text='hi')
        assert is_text_content(tc) is True

    def test_is_text_content_duck_typed(self):
        obj = MagicMock()
        obj.type = 'text'
        obj.text = 'hi'
        assert is_text_content(obj) is True

    def test_is_text_content_false(self):
        obj = MagicMock()
        obj.type = 'image'
        assert is_text_content(obj) is False

    def test_class_name_in_mro(self):
        assert class_name_in_mro('hello', 'str') is True
        assert class_name_in_mro('hello', 'int') is False

    def test_class_name_in_mro_none(self):
        assert class_name_in_mro(None, 'str') is False
        assert class_name_in_mro('hi', None) is False


# ---------------------------------------------------------------------------
# Decision & Anchor tracking
# ---------------------------------------------------------------------------


class TestDecisionTracking:
    def test_track_decision(self):
        mem = _make_memory()
        d = mem.track_decision(
            description='Use Python',
            rationale='Best fit',
            decision_type=DecisionType.ARCHITECTURAL,
            context='task analysis',
            confidence=0.9,
        )
        assert d.description == 'Use Python'
        assert d.confidence == 0.9
        assert d.decision_id in mem.decisions

    def test_multiple_decisions(self):
        mem = _make_memory()
        mem.track_decision('d1', 'r1', DecisionType.ARCHITECTURAL, 'ctx')
        mem.track_decision('d2', 'r2', DecisionType.TECHNICAL, 'ctx')
        assert len(mem.decisions) == 2


class TestAnchorTracking:
    def test_add_anchor(self):
        mem = _make_memory()
        a = mem.add_anchor(
            content='critical info', category='requirement', importance=0.95
        )
        assert a.content == 'critical info'
        assert a.anchor_id in mem.anchors

    def test_anchor_importance(self):
        mem = _make_memory()
        a1 = mem.add_anchor('low', 'misc', importance=0.3)
        a2 = mem.add_anchor('high', 'critical', importance=0.99)
        assert a2.importance > a1.importance


class TestContextSummary:
    def test_empty_summary(self):
        mem = _make_memory()
        assert mem.get_context_summary() == ''

    def test_summary_with_anchors(self):
        mem = _make_memory()
        mem.add_anchor('important', 'requirement', 0.9)
        summary = mem.get_context_summary()
        assert 'Anchors' in summary
        assert 'important' in summary

    def test_summary_with_decisions(self):
        mem = _make_memory()
        mem.track_decision('use Python', 'fast', DecisionType.ARCHITECTURAL, 'ctx')
        summary = mem.get_context_summary()
        assert 'Decisions' in summary
        assert 'use Python' in summary


# ---------------------------------------------------------------------------
# _apply_user_message_formatting
# ---------------------------------------------------------------------------


class TestUserMessageFormatting:
    def test_consecutive_user_messages_separated(self):
        msgs = [
            _text_msg('user', 'first'),
            _text_msg('user', 'second'),
        ]
        result = apply_user_message_formatting(msgs)
        c = result[1].content[0]
        assert isinstance(c, TextContent) and c.text.startswith('\n\n')

    def test_non_consecutive_not_modified(self):
        msgs = [
            _text_msg('user', 'question'),
            _text_msg('assistant', 'answer'),
            _text_msg('user', 'follow-up'),
        ]
        result = apply_user_message_formatting(msgs)
        c = result[2].content[0]
        assert isinstance(c, TextContent) and not c.text.startswith('\n\n')

    def test_formatting_idempotent(self):
        msgs = [
            _text_msg('user', 'first'),
            _text_msg('user', '\n\nsecond'),
        ]
        result = apply_user_message_formatting(msgs)
        c = result[1].content[0]
        assert isinstance(c, TextContent) and c.text == '\n\nsecond'

    def test_original_not_mutated(self):
        msg = _text_msg('user', 'text')
        msgs = [_text_msg('user', 'prev'), msg]
        apply_user_message_formatting(msgs)
        c = msg.content[0]
        assert isinstance(c, TextContent) and c.text == 'text'


# ---------------------------------------------------------------------------
# _normalize_system_messages
# ---------------------------------------------------------------------------


class TestNormalizeSystemMessages:
    def test_adds_system_if_missing(self):
        mem = _make_memory()
        msgs = [_text_msg('user', 'hi')]
        result = mem._normalize_system_messages(msgs)
        assert result[0].role == 'system'

    def test_moves_system_to_front(self):
        mem = _make_memory()
        msgs = [
            _text_msg('user', 'hi'),
            _text_msg('system', 'you are helpful'),
        ]
        result = mem._normalize_system_messages(msgs)
        assert result[0].role == 'system'

    def test_deduplicates_system_messages(self):
        mem = _make_memory()
        msgs = [
            _text_msg('system', 'prompt'),
            _text_msg('system', 'duplicate'),
            _text_msg('user', 'hi'),
        ]
        result = mem._normalize_system_messages(msgs)
        system_count = sum(1 for m in result if m.role == 'system')
        assert system_count == 1

    def test_empty_messages(self):
        mem = _make_memory()
        result = mem._normalize_system_messages([])
        assert result == []


# ---------------------------------------------------------------------------
# _remove_duplicate_system_prompt_user
# ---------------------------------------------------------------------------


class TestRemoveDuplicateSystemPromptUser:
    def test_duplicate_removed(self):
        msgs = [
            _text_msg('system', 'You are helpful'),
            _text_msg('user', 'You are helpful'),
            _text_msg('user', 'actual question'),
        ]
        result = remove_duplicate_system_prompt_user(msgs)
        assert len(result) == 2
        c = result[1].content[0]
        assert isinstance(c, TextContent) and c.text == 'actual question'

    def test_different_content_preserved(self):
        msgs = [
            _text_msg('system', 'system prompt'),
            _text_msg('user', 'different question'),
        ]
        result = remove_duplicate_system_prompt_user(msgs)
        assert len(result) == 2

    def test_single_message(self):
        msgs = [_text_msg('system', 'prompt')]
        result = remove_duplicate_system_prompt_user(msgs)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# _extract_first_text
# ---------------------------------------------------------------------------


class TestExtractFirstText:
    def test_text_content(self):
        msg = _text_msg('user', 'hello')
        assert extract_first_text(msg) == 'hello'

    def test_none_message(self):
        assert extract_first_text(None) is None

    def test_no_content(self):
        msg = Message(role='user', content=[])
        assert extract_first_text(msg) is None


# ---------------------------------------------------------------------------
# Memory store/recall (vector store disabled)
# ---------------------------------------------------------------------------


class TestMemoryStoreRecall:
    def test_store_no_vector_store(self):
        mem = _make_memory()
        # Should be a no-op, not raise
        mem.store_in_memory('ev1', 'user', 'test content')

    def test_recall_no_vector_store(self):
        mem = _make_memory()
        result = mem.recall_from_memory('query')
        assert result == []

    def test_store_with_mock_vector_store(self):
        mem = _make_memory()
        cast(Any, mem._ctx).vector_store = MagicMock()
        mem.store_in_memory('ev1', 'user', 'content', {'key': 'val'})
        cast(Any, mem._ctx).vector_store.add.assert_called_once()

    def test_recall_with_mock_vector_store(self):
        mem = _make_memory()
        cast(Any, mem._ctx).vector_store = MagicMock()
        cast(Any, mem._ctx).vector_store.search.return_value = [{'content': 'result'}]
        result = mem.recall_from_memory('query', k=3)
        assert len(result) == 1
        cast(Any, mem._ctx).vector_store.search.assert_called_once_with('query', k=3)

    def test_process_events_indexes_high_value_events_for_semantic_recall(self):
        mem = _make_memory()
        user_msg = MessageAction(content='Need a migration plan for auth tables')
        user_msg.source = EventSource.USER
        user_msg.id = 11

        cast(Any, mem._ctx).vector_store = MagicMock()
        cast(Any, mem._ctx).delete_by_ids = MagicMock()

        mem.process_events([user_msg], initial_user_action=user_msg)

        cast(Any, mem._ctx).vector_store.add.assert_called_once()
        add_kwargs = cast(Any, mem._ctx).vector_store.add.call_args.kwargs
        assert add_kwargs['step_id'] == 'event_11'
        assert add_kwargs['role'] == 'user'
        assert 'migration plan' in add_kwargs['content_text']

    def test_process_events_does_not_reindex_same_event_twice_in_session(self):
        mem = _make_memory()
        user_msg = MessageAction(content='Remember this requirement')
        user_msg.source = EventSource.USER
        user_msg.id = 12

        cast(Any, mem._ctx).vector_store = MagicMock()
        cast(Any, mem._ctx).delete_by_ids = MagicMock()

        mem.process_events([user_msg], initial_user_action=user_msg)
        mem.process_events([user_msg], initial_user_action=user_msg)

        cast(Any, mem._ctx).vector_store.add.assert_called_once()
