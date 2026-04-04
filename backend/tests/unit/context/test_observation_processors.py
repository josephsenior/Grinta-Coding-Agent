"""Tests for backend.context.observation_processors."""

from __future__ import annotations

from types import SimpleNamespace

from backend.context.observation_processors import (
    _get_observation_content,
    _handle_simple_observation,
    convert_observation_to_message,
)
from backend.core.message import TextContent
from backend.ledger.observation import (
    CmdOutputObservation,
    ErrorObservation,
    FileEditObservation,
    FileReadObservation,
    MCPObservation,
    UserRejectObservation,
)
from backend.ledger.observation.agent import AgentCondensationObservation

# ── _get_observation_content ─────────────────────────────────────────


class TestGetObservationContent:
    def test_content_attr(self):
        obs = SimpleNamespace(content='hello')
        assert _get_observation_content(obs) == 'hello'  # type: ignore[arg-type]

    def test_message_attr(self):
        obs = SimpleNamespace(message='msg')
        assert _get_observation_content(obs) == 'msg'  # type: ignore[arg-type]

    def test_fallback_str(self):
        obs = SimpleNamespace()
        result = _get_observation_content(obs)  # type: ignore[arg-type]
        assert isinstance(result, str)


# ── _handle_simple_observation ───────────────────────────────────────


class TestHandleSimpleObservation:
    def test_basic(self):
        obs = SimpleNamespace(content='output')
        msg = _handle_simple_observation(obs, None)  # type: ignore[arg-type]
        assert msg.role == 'user'
        assert msg.content[0].text == 'output'  # type: ignore[union-attr]

    def test_with_prefix_and_suffix(self):
        obs = SimpleNamespace(content='body')
        msg = _handle_simple_observation(obs, None, prefix='P:', suffix=':S')  # type: ignore[arg-type]
        assert msg.content[0].text == 'P:body:S'  # type: ignore[union-attr]

    def test_truncation(self):
        obs = SimpleNamespace(content='x' * 200)
        msg = _handle_simple_observation(obs, 50)  # type: ignore[arg-type]
        assert len(msg.content[0].text) < 200  # type: ignore[union-attr]


# ── convert_observation_to_message ───────────────────────────────────


class TestConvertObservation:
    def test_error_observation(self):
        obs = ErrorObservation(content='bad thing')
        msg = convert_observation_to_message(obs, max_message_chars=None)
        assert 'bad thing' in msg.content[0].text  # type: ignore[union-attr]
        assert '[ERROR' in msg.content[0].text  # type: ignore[union-attr]

    def test_user_reject_observation(self):
        obs = UserRejectObservation(content='no thanks')
        msg = convert_observation_to_message(obs, max_message_chars=None)
        assert 'no thanks' in msg.content[0].text  # type: ignore[union-attr]
        assert 'rejected' in msg.content[0].text.lower()  # type: ignore[union-attr]

    def test_file_read_observation(self):
        obs = FileReadObservation(content='file content', path='/tmp/x.py')
        msg = convert_observation_to_message(obs, max_message_chars=None)
        assert '[FILE_READ' in msg.content[0].text  # type: ignore[union-attr]
        assert 'file content' in msg.content[0].text  # type: ignore[union-attr]

    def test_file_edit_observation(self):
        obs = FileEditObservation(
            content='edited',
            path='/tmp/x.py',
            old_content='original',
            new_content='edited',
            prev_exist=True,
        )
        msg = convert_observation_to_message(obs, max_message_chars=None)
        assert msg.role == 'user'

    def test_mcp_observation(self):
        obs = MCPObservation(content='mcp result')
        msg = convert_observation_to_message(obs, max_message_chars=None)
        assert '[MCP_RESULT' in msg.content[0].text  # type: ignore[union-attr]
        assert 'mcp result' in msg.content[0].text  # type: ignore[union-attr]

    def test_cmd_output_observation(self):
        obs = CmdOutputObservation(
            content='output text',
            command='ls',
            command_id=1,
        )
        msg = convert_observation_to_message(obs, max_message_chars=None)
        assert msg.role == 'user'

    def test_condensation_observation_restores_scratchpad_and_working_memory(
        self, monkeypatch
    ):
        monkeypatch.setattr(
            'backend.context.observation_processors._load_scratchpad_snapshot',
            lambda: '\nSCRATCHPAD\n',
        )
        monkeypatch.setattr(
            'backend.context.observation_processors._load_working_memory_snapshot',
            lambda: '\nWORKING_MEMORY\n',
        )
        obs = AgentCondensationObservation(content='summary')

        msg = convert_observation_to_message(obs, max_message_chars=None)

        content = msg.content[0]
        assert isinstance(content, TextContent)
        text = content.text
        assert 'summary' in text
        assert 'SCRATCHPAD' in text
        assert 'WORKING_MEMORY' in text
