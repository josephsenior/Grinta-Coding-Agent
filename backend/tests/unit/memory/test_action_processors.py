"""Tests for backend.memory.action_processors – stateless conversion helpers."""

from __future__ import annotations


from backend.core.message import TextContent
from backend.events.action import (
    AgentThinkAction,
    CmdRunAction,
    MessageAction,
)
from backend.events.action.message import SystemMessageAction
from backend.events.event import EventSource
from backend.memory.action_processors import (
    _handle_message_action,
    _handle_system_message_action,
    _handle_user_cmd_action,
    _is_tool_based_action,
    _role_from_source,
    convert_action_to_messages,
)


# ── _is_tool_based_action ───────────────────────────────────────────


class TestIsToolBasedAction:
    def test_agent_think(self):
        action = AgentThinkAction(thought="hmm")
        assert _is_tool_based_action(action) is True

    def test_cmd_run_agent_source(self):
        action = CmdRunAction(command="echo hi")
        action._source = EventSource.AGENT
        assert _is_tool_based_action(action) is True

    def test_cmd_run_user_source(self):
        action = CmdRunAction(command="echo hi")
        action._source = EventSource.USER
        assert _is_tool_based_action(action) is False

    def test_message_action_not_tool_based(self):
        action = MessageAction(content="hello")
        assert _is_tool_based_action(action) is False


# ── _role_from_source ────────────────────────────────────────────────


class TestRoleFromSource:
    def test_user_source(self):
        assert _role_from_source(EventSource.USER) == "user"

    def test_agent_source(self):
        assert _role_from_source(EventSource.AGENT) == "assistant"

    def test_none_source(self):
        assert _role_from_source(None) == "assistant"

    def test_string_user(self):
        assert _role_from_source("user") == "user"


# ── _handle_message_action ──────────────────────────────────────────


class TestHandleMessageAction:
    def test_user_message(self):
        action = MessageAction(content="hello")
        action._source = EventSource.USER
        msgs = _handle_message_action(action, vision_is_active=False)
        assert len(msgs) == 1
        assert msgs[0].role == "user"
        part = msgs[0].content[0]
        assert isinstance(part, TextContent) and part.text == "hello"

    def test_agent_message(self):
        action = MessageAction(content="reply")
        action._source = EventSource.AGENT
        msgs = _handle_message_action(action, vision_is_active=False)
        assert msgs[0].role == "assistant"

    def test_with_images_user(self):
        action = MessageAction(content="look", image_urls=["http://img.png"])
        action._source = EventSource.USER
        msgs = _handle_message_action(action, vision_is_active=True)
        # Should have text + image label + image content
        assert len(msgs[0].content) >= 2

    def test_user_message_with_file_urls_appends_paths(self):
        action = MessageAction(
            content="read these",
            file_urls=["notes.txt", "src/app.py"],
        )
        action._source = EventSource.USER
        msgs = _handle_message_action(action, vision_is_active=False)
        assert len(msgs) == 1
        text = msgs[0].content[0]
        assert isinstance(text, TextContent)
        assert "read these" in text.text
        assert "notes.txt" in text.text
        assert "src/app.py" in text.text

    def test_user_message_file_urls_only(self):
        action = MessageAction(content="", file_urls=["a.md"])
        action._source = EventSource.USER
        msgs = _handle_message_action(action, vision_is_active=False)
        part = msgs[0].content[0]
        assert isinstance(part, TextContent) and "a.md" in part.text


# ── _handle_user_cmd_action ─────────────────────────────────────────


class TestHandleUserCmdAction:
    def test_formats_command(self):
        action = CmdRunAction(command="ls -la")
        msgs = _handle_user_cmd_action(action)
        assert len(msgs) == 1
        part = msgs[0].content[0]
        assert isinstance(part, TextContent) and "ls -la" in part.text
        assert msgs[0].role == "user"


# ── _handle_system_message_action ───────────────────────────────────


class TestHandleSystemMessageAction:
    def test_formats_system(self):
        action = SystemMessageAction(content="You are an agent.")
        msgs = _handle_system_message_action(action)
        assert len(msgs) == 1
        assert msgs[0].role == "system"
        part = msgs[0].content[0]
        assert isinstance(part, TextContent) and part.text == "You are an agent."


# ── convert_action_to_messages ───────────────────────────────────────


class TestConvertActionToMessages:
    def test_system_message_action(self):
        action = SystemMessageAction(content="sys")
        result = convert_action_to_messages(action, {})
        assert len(result) == 1
        assert result[0].role == "system"

    def test_message_action_user(self):
        action = MessageAction(content="hi")
        action._source = EventSource.USER
        result = convert_action_to_messages(action, {})
        assert result[0].role == "user"

    def test_unknown_action_returns_empty(self):
        """Unrecognized action types produce empty list."""
        from backend.events.action import NullAction

        action = NullAction()
        result = convert_action_to_messages(action, {})
        assert result == []
