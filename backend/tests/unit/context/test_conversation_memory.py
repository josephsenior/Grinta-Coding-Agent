"""Unit tests for backend.context.memory.conversation_memory — event→message conversion."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from backend.context.memory.conversation_memory import ContextMemory
from backend.context.memory.types import DecisionType
from backend.context.prompt.message_formatting import (
    apply_user_message_formatting,
    class_name_in_mro,
    extract_first_text,
    is_text_content,
    message_with_text,
    remove_duplicate_system_prompt_user,
)
from backend.context.prompt.turn_context import is_turn_context_text
from backend.core.message import Message, TextContent
from backend.inference.tool_support.tool_result_format import decode_tool_result_payload
from backend.integrations.mcp.mcp_utils import call_tool_mcp
from backend.ledger.action import MessageAction
from backend.ledger.action.browser_tool import BrowserToolAction
from backend.ledger.action.mcp import MCPAction
from backend.ledger.action.search import GlobAction
from backend.ledger.event import EventSource
from backend.ledger.infra.tool import ToolCallMetadata, build_tool_call_metadata
from backend.ledger.observation import (
    AgentCondensationObservation,
    AgentThinkObservation,
    ErrorObservation,
)
from backend.ledger.observation.commands import CmdOutputObservation
from backend.ledger.observation.files import FileEditObservation
from backend.ledger.observation.mcp import MCPObservation
from backend.ledger.observation.search import GlobObservation


@pytest.fixture(autouse=True)
def _clear_session_id() -> None:
    """Reset session contextvar between tests so tenants don't leak."""
    try:
        from backend.engine.tools.working_memory import set_current_session_id

        set_current_session_id(None)
    except Exception:
        pass


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
    pm.get_system_message.return_value = 'You are Grinta, an expert AI coding agent.'
    pm.get_mcp_user_addendum.return_value = ''
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


class TestMcpUserAddendum:
    def test_normalize_system_messages_inserts_mcp_addendum_after_system(self):
        mem = _make_memory()
        prompt_manager = cast(MagicMock, mem.prompt_manager)
        prompt_manager.get_mcp_user_addendum.return_value = (
            '<MCP_TOOLS>\n`github_search`\n</MCP_TOOLS>'
        )

        messages = [_text_msg('user', 'Implement the fix')]

        normalized = mem._normalize_system_messages(messages)

        assert normalized[0].role == 'system'
        assert normalized[1].role == 'system'
        mcp_text = extract_first_text(normalized[1])
        assert is_turn_context_text(mcp_text)
        assert '<MCP_TOOLS>\n`github_search`\n</MCP_TOOLS>' in mcp_text
        assert normalized[2].role == 'user'
        assert extract_first_text(normalized[2]) == 'Implement the fix'

    def test_dynamic_snapshots_do_not_modify_leading_system_prefix(self):
        mem = _make_memory()
        prompt_manager = cast(MagicMock, mem.prompt_manager)
        prompt_manager.get_mcp_user_addendum.return_value = (
            '<MCP_TOOLS>live</MCP_TOOLS>'
        )
        mem.get_context_summary = MagicMock(  # type: ignore[method-assign]
            return_value='<SESSION_CONTEXT>now</SESSION_CONTEXT>'
        )

        normalized = mem._normalize_system_messages(
            [_text_msg('user', 'Implement the fix')]
        )

        assert extract_first_text(normalized[0]) == (
            'You are Grinta, an expert AI coding agent.'
        )
        assert [message.role for message in normalized] == [
            'system',
            'system',
            'system',
            'user',
        ]
        assert all(
            is_turn_context_text(extract_first_text(message))
            for message in normalized[1:3]
        )
        assert '<MCP_TOOLS>live</MCP_TOOLS>' in extract_first_text(normalized[1])
        assert '<SESSION_CONTEXT>now</SESSION_CONTEXT>' in extract_first_text(
            normalized[2]
        )

    def test_repeated_normalization_replaces_memory_snapshots(self):
        mem = _make_memory()
        prompt_manager = cast(MagicMock, mem.prompt_manager)
        prompt_manager.get_mcp_user_addendum.return_value = '<MCP_TOOLS>v1</MCP_TOOLS>'
        mem.get_context_summary = MagicMock(  # type: ignore[method-assign]
            return_value='<SESSION_CONTEXT>v1</SESSION_CONTEXT>'
        )
        messages = mem._normalize_system_messages([_text_msg('user', 'Continue')])

        prompt_manager.get_mcp_user_addendum.return_value = '<MCP_TOOLS>v2</MCP_TOOLS>'
        mem.get_context_summary.return_value = (  # type: ignore[attr-defined]
            '<SESSION_CONTEXT>v2</SESSION_CONTEXT>'
        )
        normalized = mem._normalize_system_messages(messages)
        rendered = '\n'.join(
            extract_first_text(message) or '' for message in normalized
        )

        assert rendered.count('kind="mcp-catalog"') == 1
        assert rendered.count('kind="session-summary"') == 1
        assert '<MCP_TOOLS>v1</MCP_TOOLS>' not in rendered
        assert '<SESSION_CONTEXT>v1</SESSION_CONTEXT>' not in rendered
        assert '<MCP_TOOLS>v2</MCP_TOOLS>' in rendered
        assert '<SESSION_CONTEXT>v2</SESSION_CONTEXT>' in rendered
        assert normalized[-1].role == 'user'
        assert extract_first_text(normalized[-1]) == 'Continue'

    def test_snapshot_replacement_does_not_change_tool_results(self):
        mem = _make_memory()
        mem.get_context_summary = MagicMock(  # type: ignore[method-assign]
            return_value='<SESSION_CONTEXT>current</SESSION_CONTEXT>'
        )
        tool_result = Message(
            role='tool',
            content=[TextContent(text='complete unmodified tool output')],
            tool_call_id='call-1',
            name='read_file',
        )
        messages = [
            _text_msg('system', 'stable'),
            _text_msg(
                'system',
                '<GRINTA_TURN_CONTEXT kind="session-summary">\nold\n'
                '</GRINTA_TURN_CONTEXT>',
            ),
            tool_result,
            _text_msg('user', 'Continue'),
        ]

        normalized = mem._normalize_system_messages(messages)

        retained = next(message for message in normalized if message.role == 'tool')
        assert retained is tool_result
        assert extract_first_text(retained) == 'complete unmodified tool output'


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
        message_text = extract_first_text(tool_messages['call_5'])
        assert message_text is not None
        payload = decode_tool_result_payload(message_text)
        assert payload is not None
        assert payload[0] == 'checkpoint'
        assert isinstance(payload[1], dict)
        assert payload[1]['tool_result'] == obs.tool_result
        assert json.loads(payload[1]['message']) == obs.tool_result

    def test_structured_tool_error_is_emitted_as_one_canonical_object(self):
        mem = _make_memory()
        obs = ErrorObservation(content='multi_edit syntax validation failed.')
        obs.error_id = 'SYNTAX_VALIDATION_FAILED'
        obs.tool_result = {
            'tool': 'file_edit',
            'ok': False,
            'error_code': 'SYNTAX_VALIDATION_FAILED',
            'path': 'src/app.py',
            'line': 12,
        }
        obs.tool_call_metadata = ToolCallMetadata(
            function_name='multiedit',
            tool_call_id='call_error',
            model_response={'id': 'resp_error'},
            total_calls_in_response=1,
        )
        tool_messages: dict[str, Message] = {}

        out = mem._process_observation(
            obs,
            tool_call_id_to_message=tool_messages,
            max_message_chars=None,
        )

        assert not out
        message_text = extract_first_text(tool_messages['call_error'])
        assert message_text is not None
        payload = decode_tool_result_payload(message_text)
        assert payload is not None
        assert payload[0] == 'multiedit'
        content = payload[1]
        assert isinstance(content, dict)
        assert content['error_code'] == 'SYNTAX_VALIDATION_FAILED'
        assert content['message'] == 'multi_edit syntax validation failed.'
        assert 'tool_result' not in content
        assert '[Error occurred in processing last action]' not in message_text


class TestToolPairingMessageShape:
    @staticmethod
    def _tool_meta(tool_call_id: str) -> ToolCallMetadata:
        response_obj = SimpleNamespace(
            id=f'resp_{tool_call_id}',
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        role='assistant',
                        content='',
                        tool_calls=[
                            SimpleNamespace(
                                id=tool_call_id,
                                type='function',
                                function=SimpleNamespace(
                                    name='browser',
                                    arguments='{"command":"navigate"}',
                                ),
                            )
                        ],
                    )
                )
            ],
        )
        return build_tool_call_metadata(
            function_name='browser',
            tool_call_id=tool_call_id,
            response_obj=response_obj,
            total_calls_in_response=1,
        )

    @staticmethod
    def _tool_meta_for_name(tool_name: str, tool_call_id: str) -> ToolCallMetadata:
        response_obj = SimpleNamespace(
            id=f'resp_{tool_call_id}',
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        role='assistant',
                        content='Inspecting the workspace.',
                        tool_calls=[
                            SimpleNamespace(
                                id=tool_call_id,
                                type='function',
                                function=SimpleNamespace(
                                    name=tool_name,
                                    arguments='{"pattern":"**/*.py"}',
                                ),
                            )
                        ],
                    )
                )
            ],
        )
        return build_tool_call_metadata(
            function_name=tool_name,
            tool_call_id=tool_call_id,
            response_obj=response_obj,
            total_calls_in_response=1,
        )

    def test_process_events_keeps_assistant_tool_call_when_observation_has_metadata(
        self,
    ):
        mem = _make_memory()
        initial_user = MessageAction(content='check example.com')
        initial_user.source = EventSource.USER

        action = BrowserToolAction(
            command='navigate', params={'url': 'https://example.com'}
        )
        action.source = EventSource.AGENT
        action.tool_call_metadata = self._tool_meta('tc_ok')

        obs = CmdOutputObservation(
            content='Navigated to https://example.com',
            command='browser navigate',
            metadata={'exit_code': 0},
        )
        obs.tool_call_metadata = action.tool_call_metadata

        messages = mem.process_events(
            condensed_history=[action, obs],
            initial_user_action=initial_user,
            max_message_chars=None,
            vision_is_active=False,
        )

        assert any(m.role == 'assistant' and m.tool_calls for m in messages)
        assert any(m.role == 'tool' for m in messages)

    def test_process_events_keeps_discovery_tool_action_and_observation(self):
        mem = _make_memory()
        initial_user = MessageAction(content='inspect the repo')
        initial_user.source = EventSource.USER

        action = GlobAction(pattern='**/*.py')
        action.source = EventSource.AGENT
        action.tool_call_metadata = self._tool_meta_for_name('glob', 'tc_glob')

        obs = GlobObservation(
            content='backend/context/conversation_memory.py',
            pattern='**/*.py',
            files=['backend/context/conversation_memory.py'],
            file_count=1,
        )
        obs.tool_call_metadata = action.tool_call_metadata
        obs.tool_result = {'ok': True, 'action': 'glob', 'observation': 'glob_result'}

        messages = mem.process_events(
            condensed_history=[action, obs],
            initial_user_action=initial_user,
            max_message_chars=None,
            vision_is_active=False,
        )

        assistant = next(m for m in messages if m.role == 'assistant' and m.tool_calls)
        tool = next(m for m in messages if m.role == 'tool')
        assert assistant.tool_calls[0].id == 'tc_glob'
        assert tool.tool_call_id == 'tc_glob'
        assert tool.name == 'glob'

    def test_process_events_drops_unpaired_assistant_tool_call_without_observation_metadata(
        self,
    ):
        mem = _make_memory()
        initial_user = MessageAction(content='check example.com')
        initial_user.source = EventSource.USER

        action = BrowserToolAction(
            command='navigate', params={'url': 'https://example.com'}
        )
        action.source = EventSource.AGENT
        action.tool_call_metadata = self._tool_meta('tc_missing')

        obs = CmdOutputObservation(
            content='Navigated to https://example.com',
            command='browser navigate',
            metadata={'exit_code': 0},
        )
        # Intentional: no obs.tool_call_metadata, this becomes role=user.

        messages = mem.process_events(
            condensed_history=[action, obs],
            initial_user_action=initial_user,
            max_message_chars=None,
            vision_is_active=False,
        )

        assert not any(m.role == 'assistant' and m.tool_calls for m in messages)
        assert not any(m.role == 'tool' for m in messages)
        assert sum(1 for m in messages if m.role == 'user') >= 2


class TestPromptRenderCache:
    def test_reuses_stable_observation_rendering(self, monkeypatch):
        mem = _make_memory()
        initial_user = MessageAction(content='start')
        initial_user.source = EventSource.USER
        obs = CmdOutputObservation(content='ok', command='pytest -q', exit_code=0)

        calls = 0
        original = mem._get_message_for_observation

        def counted(*args, **kwargs):
            nonlocal calls
            calls += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(mem, '_get_message_for_observation', counted)

        mem.process_events([obs], initial_user, max_message_chars=None)
        mem.process_events([obs], initial_user, max_message_chars=None)

        assert calls == 1

    def test_file_hash_change_invalidates_render_cache(self, monkeypatch):
        mem = _make_memory()
        initial_user = MessageAction(content='start')
        initial_user.source = EventSource.USER
        obs = FileEditObservation(
            content='edited',
            path='src/app.py',
            new_content='print("one")\n',
            new_content_hash='hash_one',
        )

        calls = 0
        original = mem._get_message_for_observation

        def counted(*args, **kwargs):
            nonlocal calls
            calls += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(mem, '_get_message_for_observation', counted)

        mem.process_events([obs], initial_user, max_message_chars=None)
        obs.new_content_hash = 'hash_two'
        mem.process_events([obs], initial_user, max_message_chars=None)

        assert calls == 2

    def test_tool_observations_are_not_render_cached(self, monkeypatch):
        mem = _make_memory()
        initial_user = MessageAction(content='start')
        initial_user.source = EventSource.USER
        obs = MCPObservation(content='{"ok": true}', name='remote_tool', arguments={})
        obs.tool_call_metadata = ToolCallMetadata(
            function_name='remote_tool',
            tool_call_id='call_uncached',
            model_response={'id': 'resp_uncached'},
            total_calls_in_response=1,
        )

        calls = 0
        original = mem._get_message_for_observation

        def counted(*args, **kwargs):
            nonlocal calls
            calls += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(mem, '_get_message_for_observation', counted)

        mem.process_events([obs], initial_user, max_message_chars=None)
        mem.process_events([obs], initial_user, max_message_chars=None)

        assert calls == 2


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
        import backend.context.memory.conversation_memory as cm

        fake_store = MagicMock(name='vector_store')
        monkeypatch.setattr(
            cm, 'EnhancedVectorStore', MagicMock(return_value=fake_store)
        )

        monkeypatch.setattr(
            'backend.utils.optional_extras.is_rag_extra_available',
            lambda: True,
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
    def test_process_events_keeps_stable_prompt_and_current_context_packet(self):
        mem = _make_memory()
        user = MessageAction(content='Continue the task')
        user.source = EventSource.USER
        user.id = 1
        packet = AgentCondensationObservation(
            content='<CONTEXT_PACKET>current state</CONTEXT_PACKET>',
            is_working_set=True,
        )
        packet.id = 2

        result = mem.process_events([packet, user], user)
        system_texts = [
            message.content[0].text for message in result if message.role == 'system'
        ]

        assert system_texts[0] == 'You are Grinta, an expert AI coding agent.'
        assert system_texts[1] == '<CONTEXT_PACKET>current state</CONTEXT_PACKET>'
        assert len(system_texts) == 2

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

    def test_preserves_distinct_system_messages(self):
        mem = _make_memory()
        msgs = [
            _text_msg('system', 'prompt'),
            _text_msg('system', 'duplicate'),
            _text_msg('user', 'hi'),
        ]
        result = mem._normalize_system_messages(msgs)
        system_count = sum(1 for m in result if m.role == 'system')
        assert system_count == 2
        assert [m.content[0].text for m in result[:2]] == ['prompt', 'duplicate']

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
        cast(Any, mem._ctx).vector_store.search.assert_called_once()
        call = cast(Any, mem._ctx).vector_store.search.call_args
        assert call.args[0] == 'query'
        assert call.kwargs['k'] == 3

    def test_process_events_indexes_high_value_events_for_semantic_recall(self):
        mem = _make_memory()
        user_msg = MessageAction(content='Need a migration plan for auth tables')
        user_msg.source = EventSource.USER
        user_msg.id = 11

        cast(Any, mem._ctx).vector_store = MagicMock()
        cast(Any, mem._ctx).delete_by_ids = MagicMock()

        mem.process_events([user_msg], initial_user_action=user_msg)
        # The semantic indexer now writes through a background worker
        # so the prompt-assembly hot path stays non-blocking. Flush the
        # queue synchronously to make the test deterministic.
        mem.shutdown()

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
        # Flush the background indexer so the assertion is deterministic.
        mem.shutdown()

        cast(Any, mem._ctx).vector_store.add.assert_called_once()
