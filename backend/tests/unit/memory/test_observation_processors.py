"""Tests for backend.memory.observation_processors."""

from __future__ import annotations

from types import SimpleNamespace


from backend.memory.observation_processors import (
    _get_observation_content,
    _handle_simple_observation,
    convert_observation_to_message,
)
from backend.events.observation import (
    CmdOutputObservation,
    ErrorObservation,
    FileEditObservation,
    FileReadObservation,
    MCPObservation,
    UserRejectObservation,
)

# ── _get_observation_content ─────────────────────────────────────────


class TestGetObservationContent:
    def test_content_attr(self):
        obs = SimpleNamespace(content="hello")
        assert _get_observation_content(obs) == "hello"

    def test_message_attr(self):
        obs = SimpleNamespace(message="msg")
        assert _get_observation_content(obs) == "msg"

    def test_fallback_str(self):
        obs = SimpleNamespace()
        result = _get_observation_content(obs)
        assert isinstance(result, str)


# ── _handle_simple_observation ───────────────────────────────────────


class TestHandleSimpleObservation:
    def test_basic(self):
        obs = SimpleNamespace(content="output")
        msg = _handle_simple_observation(obs, None)
        assert msg.role == "user"
        assert msg.content[0].text == "output"

    def test_with_prefix_and_suffix(self):
        obs = SimpleNamespace(content="body")
        msg = _handle_simple_observation(obs, None, prefix="P:", suffix=":S")
        assert msg.content[0].text == "P:body:S"

    def test_truncation(self):
        obs = SimpleNamespace(content="x" * 200)
        msg = _handle_simple_observation(obs, 50)
        assert len(msg.content[0].text) < 200


# ── convert_observation_to_message ───────────────────────────────────


class TestConvertObservation:
    def test_error_observation(self):
        obs = ErrorObservation(content="bad thing")
        msg = convert_observation_to_message(obs, max_message_chars=None)
        assert "bad thing" in msg.content[0].text
        assert "[ERROR" in msg.content[0].text

    def test_user_reject_observation(self):
        obs = UserRejectObservation(content="no thanks")
        msg = convert_observation_to_message(obs, max_message_chars=None)
        assert "no thanks" in msg.content[0].text
        assert "rejected" in msg.content[0].text.lower()

    def test_file_read_observation(self):
        obs = FileReadObservation(content="file content", path="/tmp/x.py")
        msg = convert_observation_to_message(obs, max_message_chars=None)
        assert "[FILE_READ" in msg.content[0].text
        assert "file content" in msg.content[0].text

    def test_file_edit_observation(self):
        obs = FileEditObservation(
            content="edited",
            path="/tmp/x.py",
            old_content="original",
            new_content="edited",
            prev_exist=True,
        )
        msg = convert_observation_to_message(obs, max_message_chars=None)
        assert msg.role == "user"

    def test_mcp_observation(self):
        obs = MCPObservation(content="mcp result")
        msg = convert_observation_to_message(obs, max_message_chars=None)
        assert "[MCP_RESULT" in msg.content[0].text
        assert "mcp result" in msg.content[0].text

    def test_cmd_output_observation(self):
        obs = CmdOutputObservation(
            content="output text",
            command="ls",
            command_id=1,
        )
        msg = convert_observation_to_message(obs, max_message_chars=None)
        assert msg.role == "user"
