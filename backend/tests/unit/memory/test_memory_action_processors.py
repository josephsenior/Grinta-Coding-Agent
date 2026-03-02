"""Tests for backend.memory.action_processors — action-to-message conversion."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock


from backend.core.message import TextContent
from backend.events.action.message import SystemMessageAction
from backend.events.event import EventSource
from backend.memory.action_processors import (
    _build_think_action_message,
    _content_from_assistant_message,
    _convert_tool_calls,
    _ensure_tool_call_function,
    _handle_message_action,
    _handle_system_message_action,
    _handle_user_cmd_action,
    _is_tool_based_action,
    _role_from_assistant_message,
    _role_from_source,
    _should_emit_user_tool_request,
    convert_action_to_messages,
)


# ── _is_tool_based_action ────────────────────────────────────────────


class TestIsToolBasedActionProc:
    def test_file_edit_action_is_tool(self):
        from backend.events.action import FileEditAction

        action = MagicMock(spec=FileEditAction)
        action.source = EventSource.AGENT
        assert _is_tool_based_action(action) is True

    def test_cmd_run_from_agent_is_tool(self):
        from backend.events.action import CmdRunAction

        action = MagicMock(spec=CmdRunAction)
        action.source = EventSource.AGENT
        assert _is_tool_based_action(action) is True

    def test_cmd_run_from_user_is_not_tool(self):
        from backend.events.action import CmdRunAction

        action = MagicMock(spec=CmdRunAction)
        action.source = EventSource.USER
        assert _is_tool_based_action(action) is False

    def test_message_action_is_not_tool(self):
        from backend.events.action import MessageAction

        action = MagicMock(spec=MessageAction)
        action.source = EventSource.USER
        assert _is_tool_based_action(action) is False


# ── _should_emit_user_tool_request ────────────────────────────────────


class TestShouldEmitUserToolRequestProc:
    def test_user_no_metadata_returns_true(self):
        action = MagicMock()
        action.source = EventSource.USER
        action.tool_call_metadata = None
        assert _should_emit_user_tool_request(action) is True

    def test_user_with_metadata_returns_false(self):
        action = MagicMock()
        action.source = EventSource.USER
        action.tool_call_metadata = MagicMock()
        assert _should_emit_user_tool_request(action) is False

    def test_agent_returns_false(self):
        action = MagicMock()
        action.source = EventSource.AGENT
        action.tool_call_metadata = None
        assert _should_emit_user_tool_request(action) is False


# ── _build_think_action_message ───────────────────────────────────────


class TestBuildThinkActionMessageProc:
    def test_creates_assistant_message_with_thought(self):
        action = MagicMock()
        action.thought = "I should check the file first"
        msgs = _build_think_action_message(action)
        assert len(msgs) == 1
        assert msgs[0].role == "assistant"
        part = msgs[0].content[0]
        assert isinstance(part, TextContent) and "I should check the file first" in part.text

    def test_empty_thought(self):
        action = MagicMock()
        action.thought = ""
        msgs = _build_think_action_message(action)
        assert len(msgs) == 1


# ── _role_from_assistant_message ──────────────────────────────────────


class TestRoleFromAssistantMessageProc:
    def test_valid_roles(self):
        for role in ("user", "system", "assistant", "tool"):
            msg = MagicMock()
            msg.role = role
            assert _role_from_assistant_message(msg) == role

    def test_invalid_role_defaults_to_assistant(self):
        msg = MagicMock()
        msg.role = "invalid"
        assert _role_from_assistant_message(msg) == "assistant"

    def test_missing_role_defaults_to_assistant(self):
        msg = MagicMock(spec=[])
        assert _role_from_assistant_message(msg) == "assistant"


# ── _content_from_assistant_message ───────────────────────────────────


class TestContentFromAssistantMessageProc:
    def test_string_content(self):
        msg = MagicMock()
        msg.content = "hello world"
        result = _content_from_assistant_message(msg)
        assert len(result) == 1
        part = result[0]
        assert isinstance(part, TextContent) and part.text == "hello world"

    def test_empty_string_content(self):
        msg = MagicMock()
        msg.content = "   "
        result = _content_from_assistant_message(msg)
        assert not result

    def test_none_content(self):
        msg = MagicMock()
        msg.content = None
        result = _content_from_assistant_message(msg)
        assert not result

    def test_non_string_content(self):
        msg = MagicMock()
        msg.content = 42
        result = _content_from_assistant_message(msg)
        assert len(result) == 1
        part = result[0]
        assert isinstance(part, TextContent) and "42" in part.text


# ── _role_from_source ─────────────────────────────────────────────────


class TestRoleFromSourceProc:
    def test_user_source(self):
        assert _role_from_source(EventSource.USER) == "user"

    def test_agent_source(self):
        assert _role_from_source(EventSource.AGENT) == "assistant"

    def test_string_user(self):
        assert _role_from_source("user") == "user"

    def test_string_agent(self):
        assert _role_from_source("agent") == "assistant"

    def test_none_source(self):
        assert _role_from_source(None) == "assistant"


# ── _convert_tool_calls ──────────────────────────────────────────────


class TestConvertToolCallsProc:
    def test_none_returns_none(self):
        assert _convert_tool_calls(None) is None

    def test_empty_list_returns_none(self):
        assert _convert_tool_calls([]) is None

    def test_dict_tool_call(self):
        calls = [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "read_file", "arguments": '{"path": "x.py"}'},
            }
        ]
        result = _convert_tool_calls(calls)
        assert result is not None
        assert len(result) == 1
        assert result[0].id == "call_1"

    def test_model_dump_tool_call(self):
        call = MagicMock()
        call.model_dump.return_value = {
            "id": "call_2",
            "type": "function",
            "function": {"name": "edit_file", "arguments": "{}"},
        }
        result = _convert_tool_calls([call])
        assert result is not None
        assert result[0].id == "call_2"

    def test_generates_fallback_id(self):
        call = MagicMock(spec=[])
        call.id = None
        call.type = "function"
        call.function = None
        call.arguments = None
        call.name = "test_tool"
        result = _convert_tool_calls([call])
        assert result is not None
        assert result[0].id == "tool_call_0"


# ── _ensure_tool_call_function ────────────────────────────────────────


class TestEnsureToolCallFunctionProc:
    def test_creates_function_when_missing(self):
        call_dict: dict[str, Any] = {"name": "read_file", "arguments": '{"path": "a.py"}'}
        _ensure_tool_call_function(call_dict, MagicMock(), 0)
        assert "function" in call_dict
        fn = call_dict["function"]
        assert isinstance(fn, dict) and fn["name"] == "read_file"

    def test_preserves_existing_function_dict(self):
        fn: dict[str, Any] = {"name": "edit", "arguments": "{}"}
        call_dict: dict[str, Any] = {"function": fn}
        _ensure_tool_call_function(call_dict, MagicMock(), 0)
        assert call_dict["function"]["name"] == "edit"

    def test_sets_defaults_in_existing_function(self):
        fn: dict[str, Any] = {"name": "edit"}
        call_dict: dict[str, Any] = {"function": fn}
        _ensure_tool_call_function(call_dict, MagicMock(spec=[]), 0)
        assert "arguments" in call_dict["function"]

    def test_handles_object_function(self):
        fn_obj = MagicMock()
        fn_obj.name = "obj_tool"
        fn_obj.arguments = '{"x": 1}'
        call_dict: dict[str, Any] = {"function": fn_obj}
        _ensure_tool_call_function(call_dict, MagicMock(), 0)
        fn = call_dict["function"]
        assert isinstance(fn, dict) and fn["name"] == "obj_tool"


# ── _handle_message_action ────────────────────────────────────────────


class TestHandleMessageActionProc:
    def test_user_message(self):
        from backend.events.action import MessageAction

        action = MessageAction(content="hello")
        action.source = EventSource.USER
        msgs = _handle_message_action(action, vision_is_active=False)
        assert len(msgs) == 1
        assert msgs[0].role == "user"
        part = msgs[0].content[0]
        assert isinstance(part, TextContent) and part.text == "hello"

    def test_agent_message(self):
        from backend.events.action import MessageAction

        action = MessageAction(content="response")
        action.source = EventSource.AGENT
        msgs = _handle_message_action(action, vision_is_active=False)
        assert len(msgs) == 1
        assert msgs[0].role == "assistant"

    def test_message_with_images(self):
        from backend.events.action import MessageAction

        action = MessageAction(
            content="look at this",
            image_urls=["http://example.com/img.png"],
        )
        action.source = EventSource.USER
        msgs = _handle_message_action(action, vision_is_active=True)
        assert len(msgs) == 1
        assert len(msgs[0].content) >= 2


# ── _handle_user_cmd_action ───────────────────────────────────────────


class TestHandleUserCmdActionProc:
    def test_produces_user_message(self):
        from backend.events.action import CmdRunAction

        action = CmdRunAction(command="ls -la")
        msgs = _handle_user_cmd_action(action)
        assert len(msgs) == 1
        assert msgs[0].role == "user"
        part = msgs[0].content[0]
        assert isinstance(part, TextContent) and "ls -la" in part.text


# ── _handle_system_message_action ─────────────────────────────────────


class TestHandleSystemMessageActionProc:
    def test_produces_system_message(self):
        action = SystemMessageAction(content="System alert")
        msgs = _handle_system_message_action(action)
        assert len(msgs) == 1
        assert msgs[0].role == "system"
        part = msgs[0].content[0]
        assert isinstance(part, TextContent) and part.text == "System alert"
        assert msgs[0].tool_calls is None


# ── convert_action_to_messages (integration) ──────────────────────────


class TestConvertActionToMessagesProc:
    def test_system_message_dispatches(self):
        action = SystemMessageAction(content="hi")
        msgs = convert_action_to_messages(action, {})
        assert len(msgs) == 1
        assert msgs[0].role == "system"

    def test_unknown_action_returns_empty(self):
        action = MagicMock()
        action.__class__ = type("UnknownAction", (), {})
        action.source = "user"
        action.tool_call_metadata = None
        msgs = convert_action_to_messages(action, {})
        assert msgs == []
