"""Tests for backend.context.processors.action_processors – stateless conversion helpers."""

from __future__ import annotations

from backend.context.processors.action_processors import (
    _handle_message_action,
    _handle_system_message_action,
    _handle_user_cmd_action,
    _is_tool_based_action,
    convert_action_to_messages,
)
from backend.core.message import TextContent
from backend.ledger.action import (
    AgentThinkAction,
    CmdRunAction,
    MessageAction,
)
from backend.ledger.action.message import SystemMessageAction
from backend.ledger.action.search import GlobAction
from backend.ledger.event import EventSource
from backend.ledger.infra.tool import ToolCallMetadata

# ── _is_tool_based_action ───────────────────────────────────────────


class TestIsToolBasedAction:
    def test_agent_think(self):
        action = AgentThinkAction(thought='hmm')
        assert _is_tool_based_action(action) is True

    def test_cmd_run_agent_source(self):
        action = CmdRunAction(command='echo hi')
        action._source = EventSource.AGENT
        assert _is_tool_based_action(action) is True

    def test_cmd_run_user_source(self):
        action = CmdRunAction(command='echo hi')
        action._source = EventSource.USER
        assert _is_tool_based_action(action) is False

    def test_message_action_not_tool_based(self):
        action = MessageAction(content='hello')
        assert _is_tool_based_action(action) is False

    def test_any_action_with_tool_call_metadata_is_tool_based(self):
        action = GlobAction(pattern='**/*.py')
        action.tool_call_metadata = ToolCallMetadata(
            function_name='glob',
            tool_call_id='call_glob',
            model_response={
                'id': 'resp_glob',
                'choices': [
                    {
                        'message': {
                            'role': 'assistant',
                            'content': '',
                            'tool_calls': [
                                {
                                    'id': 'call_glob',
                                    'type': 'function',
                                    'function': {
                                        'name': 'glob',
                                        'arguments': '{"pattern":"**/*.py"}',
                                    },
                                }
                            ],
                        }
                    }
                ],
            },
            total_calls_in_response=1,
        )

        assert _is_tool_based_action(action) is True


class TestToolReplayReasoningContent:
    def test_replay_preserves_reasoning_content_from_model_response(self):
        pending: dict[str, object] = {}
        action = GlobAction(pattern='**/*.py')
        action.tool_call_metadata = ToolCallMetadata(
            function_name='glob',
            tool_call_id='call_glob',
            model_response={
                'id': 'resp_glob',
                'choices': [
                    {
                        'message': {
                            'role': 'assistant',
                            'content': 'Searching.',
                            'reasoning_content': 'I should list Python files first.',
                            'tool_calls': [
                                {
                                    'id': 'call_glob',
                                    'type': 'function',
                                    'function': {
                                        'name': 'glob',
                                        'arguments': '{"pattern":"**/*.py"}',
                                    },
                                }
                            ],
                        }
                    }
                ],
            },
            total_calls_in_response=1,
        )

        convert_action_to_messages(action, pending)

        replayed = pending['resp_glob']
        assert replayed.reasoning_content == 'I should list Python files first.'

    def test_replay_falls_back_to_action_thought_when_reasoning_missing(self):
        pending: dict[str, object] = {}
        action = GlobAction(pattern='**/*.py')
        action.thought = 'Recovered from action.thought after lite strip.'
        action.tool_call_metadata = ToolCallMetadata(
            function_name='glob',
            tool_call_id='call_glob',
            model_response={
                'id': 'resp_glob',
                'choices': [
                    {
                        'message': {
                            'role': 'assistant',
                            'content': '.',
                            'tool_calls': [
                                {
                                    'id': 'call_glob',
                                    'type': 'function',
                                    'function': {
                                        'name': 'glob',
                                        'arguments': '{"pattern":"**/*.py"}',
                                    },
                                }
                            ],
                        }
                    }
                ],
            },
            total_calls_in_response=1,
        )

        convert_action_to_messages(action, pending)

        replayed = pending['resp_glob']
        assert (
            replayed.reasoning_content
            == 'Recovered from action.thought after lite strip.'
        )

    def test_replay_uses_synthetic_key_when_model_response_id_empty(self):
        pending: dict[str, object] = {}
        action = GlobAction(pattern='**/*.py')
        action.tool_call_metadata = ToolCallMetadata(
            function_name='glob',
            tool_call_id='call_glob_empty_id',
            model_response={
                'id': '',
                'choices': [
                    {
                        'message': {
                            'role': 'assistant',
                            'content': '',
                            'tool_calls': [
                                {
                                    'id': 'call_glob_empty_id',
                                    'type': 'function',
                                    'function': {
                                        'name': 'glob',
                                        'arguments': '{"pattern":"**/*.py"}',
                                    },
                                }
                            ],
                        }
                    }
                ],
            },
            total_calls_in_response=1,
        )

        convert_action_to_messages(action, pending)

        assert 'grinta-synthetic-replay:call_glob_empty_id' in pending
        assert '' not in pending or len(pending) == 1


# ── _handle_message_action ──────────────────────────────────────────


class TestHandleMessageAction:
    def test_user_message(self):
        action = MessageAction(content='hello')
        action._source = EventSource.USER
        msgs = _handle_message_action(action, vision_is_active=False)
        assert len(msgs) == 1
        assert msgs[0].role == 'user'
        part = msgs[0].content[0]
        assert isinstance(part, TextContent) and part.text == 'hello'

    def test_agent_message(self):
        action = MessageAction(content='reply')
        action._source = EventSource.AGENT
        msgs = _handle_message_action(action, vision_is_active=False)
        assert msgs[0].role == 'assistant'

    def test_transcript_only_message_is_not_sent_to_model(self):
        action = MessageAction(content='shown in transcript', transcript_only=True)
        action._source = EventSource.AGENT
        msgs = _handle_message_action(action, vision_is_active=False)
        assert msgs == []

    def test_with_images_user(self):
        action = MessageAction(content='look', image_urls=['http://img.png'])
        action._source = EventSource.USER
        msgs = _handle_message_action(action, vision_is_active=True)
        # Should have text + image label + image content
        assert len(msgs[0].content) >= 2

    def test_user_message_with_file_urls_appends_paths(self):
        action = MessageAction(
            content='read these',
            file_urls=['notes.txt', 'src/app.py'],
        )
        action._source = EventSource.USER
        msgs = _handle_message_action(action, vision_is_active=False)
        assert len(msgs) == 1
        text = msgs[0].content[0]
        assert isinstance(text, TextContent)
        assert 'read these' in text.text
        assert 'notes.txt' in text.text
        assert 'src/app.py' in text.text

    def test_user_message_file_urls_only(self):
        action = MessageAction(content='', file_urls=['a.md'])
        action._source = EventSource.USER
        msgs = _handle_message_action(action, vision_is_active=False)
        part = msgs[0].content[0]
        assert isinstance(part, TextContent) and 'a.md' in part.text


# ── _handle_user_cmd_action ─────────────────────────────────────────


class TestHandleUserCmdAction:
    def test_formats_command(self):
        action = CmdRunAction(command='ls -la')
        msgs = _handle_user_cmd_action(action)
        assert len(msgs) == 1
        part = msgs[0].content[0]
        assert isinstance(part, TextContent) and 'ls -la' in part.text
        assert msgs[0].role == 'user'


# ── _handle_system_message_action ───────────────────────────────────


class TestHandleSystemMessageAction:
    def test_formats_system(self):
        action = SystemMessageAction(content='You are an agent.')
        msgs = _handle_system_message_action(action)
        assert len(msgs) == 1
        assert msgs[0].role == 'system'
        part = msgs[0].content[0]
        assert isinstance(part, TextContent) and part.text == 'You are an agent.'


# ── convert_action_to_messages ───────────────────────────────────────


class TestConvertActionToMessages:
    def test_system_message_action(self):
        action = SystemMessageAction(content='sys')
        result = convert_action_to_messages(action, {})
        assert len(result) == 1
        assert result[0].role == 'system'

    def test_message_action_user(self):
        action = MessageAction(content='hi')
        action._source = EventSource.USER
        result = convert_action_to_messages(action, {})
        assert result[0].role == 'user'

    def test_unknown_action_returns_empty(self):
        """Unrecognized action types produce empty list."""
        from backend.ledger.action import NullAction

        action = NullAction()
        result = convert_action_to_messages(action, {})
        assert result == []
