"""Tests for strict agent-mode protocol, parser, validator, and executor gating."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from backend.engine.file_edit_protocol_agent_mode import (
    AgentModeProtocolError,
    parse_raw_edit_block,
    validate_edit_command_metadata,
)
from backend.engine.executor import OrchestratorExecutor
from backend.ledger.action import Action
from backend.ledger.action.message import MessageAction
from backend.ledger.action.files import FileEditAction
from backend.core.config.agent_config import AgentConfig


# =====================================================================
# Unit Tests for Parser and Metadata Validator
# =====================================================================

def test_parse_valid_edit_block_success():
    text = (
        "EDIT_FILE\n"
        "path: src/main.py\n"
        "command: replace_range\n"
        "start_line: 10\n"
        "end_line: 20\n"
        "\n"
        "RAW_LINES MY_DELIMITER_123\n"
        "def hello_world():\n"
        "    print('Hello World')\n"
        "END_RAW_LINES MY_DELIMITER_123\n"
    )
    result = parse_raw_edit_block(text, "MY_DELIMITER_123")
    assert result["headers"] == {
        "path": "src/main.py",
        "command": "replace_range",
        "start_line": "10",
        "end_line": "20",
    }
    assert result["content"] == "def hello_world():\n    print('Hello World')"


def test_parse_block_rejects_missing_edit_file_prefix():
    text = (
        "path: src/main.py\n"
        "command: replace_range\n"
        "RAW_LINES TOKEN\n"
        "content\n"
        "END_RAW_LINES TOKEN\n"
    )
    with pytest.raises(AgentModeProtocolError, match="Response must start with EDIT_FILE"):
        parse_raw_edit_block(text, "TOKEN")


def test_parse_block_rejects_missing_raw_lines_markers():
    text_no_start = (
        "EDIT_FILE\n"
        "path: src/main.py\n"
        "command: replace_range\n"
        "content\n"
        "END_RAW_LINES TOKEN\n"
    )
    with pytest.raises(AgentModeProtocolError, match="Missing RAW_LINES TOKEN"):
        parse_raw_edit_block(text_no_start, "TOKEN")

    text_no_end = (
        "EDIT_FILE\n"
        "path: src/main.py\n"
        "command: replace_range\n"
        "RAW_LINES TOKEN\n"
        "content\n"
    )
    with pytest.raises(AgentModeProtocolError, match="Missing END_RAW_LINES TOKEN"):
        parse_raw_edit_block(text_no_end, "TOKEN")


def test_parse_block_rejects_malformed_headers():
    text = (
        "EDIT_FILE\n"
        "path src/main.py\n"
        "command: replace_range\n"
        "RAW_LINES TOKEN\n"
        "content\n"
        "END_RAW_LINES TOKEN\n"
    )
    with pytest.raises(AgentModeProtocolError, match="Malformed header line"):
        parse_raw_edit_block(text, "TOKEN")


def test_parse_block_rejects_missing_required_headers():
    text_no_path = (
        "EDIT_FILE\n"
        "command: replace_range\n"
        "RAW_LINES TOKEN\n"
        "content\n"
        "END_RAW_LINES TOKEN\n"
    )
    with pytest.raises(AgentModeProtocolError, match="Required header 'path' is missing"):
        parse_raw_edit_block(text_no_path, "TOKEN")

    text_no_command = (
        "EDIT_FILE\n"
        "path: src/main.py\n"
        "RAW_LINES TOKEN\n"
        "content\n"
        "END_RAW_LINES TOKEN\n"
    )
    with pytest.raises(AgentModeProtocolError, match="Required header 'command' is missing"):
        parse_raw_edit_block(text_no_command, "TOKEN")


def test_parse_block_rejects_extra_trailing_prose():
    text = (
        "EDIT_FILE\n"
        "path: src/main.py\n"
        "command: replace_range\n"
        "RAW_LINES TOKEN\n"
        "content\n"
        "END_RAW_LINES TOKEN\n"
        "Extra explanation here."
    )
    with pytest.raises(AgentModeProtocolError, match="Prose or text after the raw edit block is forbidden"):
        parse_raw_edit_block(text, "TOKEN")


def test_validate_edit_command_metadata_normalization():
    # Exact command verification
    metadata_insert = {"insert_line": "5"}
    assert validate_edit_command_metadata("insert", metadata_insert) == "insert"
    assert metadata_insert["insert_line"] == 5

    metadata_range = {"start_line": "1", "end_line": "10"}
    assert validate_edit_command_metadata("replace_range", metadata_range) == "replace_range"
    assert metadata_range["start_line"] == 1
    assert metadata_range["end_line"] == 10

    # Ensure aliases and create are rejected
    for invalid_cmd in ("create", "create_file", "insert_text", "edit", "range"):
        with pytest.raises(AgentModeProtocolError, match="Unknown edit command"):
            validate_edit_command_metadata(invalid_cmd, {})


def test_validate_edit_command_metadata_failures():
    # unknown command
    with pytest.raises(AgentModeProtocolError, match="Unknown edit command"):
        validate_edit_command_metadata("invalid_cmd", {})

    # insert command missing line
    with pytest.raises(AgentModeProtocolError, match="Missing command field"):
        validate_edit_command_metadata("insert", {})

    # insert command invalid line int
    with pytest.raises(AgentModeProtocolError, match="must be an integer"):
        validate_edit_command_metadata("insert", {"insert_line": "abc"})

    # replace_range missing range fields
    with pytest.raises(AgentModeProtocolError, match="Missing command field"):
        validate_edit_command_metadata("replace_range", {"start_line": "1"})

    # replace_range invalid int types
    with pytest.raises(AgentModeProtocolError, match="must be an integer"):
        validate_edit_command_metadata("replace_range", {"start_line": "abc", "end_line": "10"})


# =====================================================================
# Unit Tests for Executor Gating
# =====================================================================

def _make_mock_executor(mode: str, delimiter_token: str) -> OrchestratorExecutor:
    """Create a partially mocked OrchestratorExecutor for testing gating."""
    executor = object.__new__(OrchestratorExecutor)
    
    # Mock planner config
    mock_config = MagicMock()
    mock_config.mode = mode
    
    mock_agent = MagicMock()
    mock_agent._current_delimiter_token = delimiter_token

    mock_planner = MagicMock()
    mock_planner._config = mock_config
    mock_planner._agent = mock_agent

    executor._planner = mock_planner
    return executor


def test_gate_plain_text_in_chat_or_ask_mode_passes_through():
    executor = _make_mock_executor(mode="chat", delimiter_token="TOKEN")
    
    original_actions = [MessageAction(content="Hello world")]
    gated_actions = executor._gate_agent_mode_plain_text(original_actions, MagicMock())
    
    # In chat mode, plain text MessageAction is returned unchanged
    assert gated_actions == original_actions


def test_gate_plain_text_in_agent_mode_rejects_pure_prose():
    executor = _make_mock_executor(mode="agent", delimiter_token="TOKEN")
    
    original_actions = [MessageAction(content="This is plain prose explanation.")]
    
    with pytest.raises(AgentModeProtocolError, match="Response must start with EDIT_FILE"):
        executor._gate_agent_mode_plain_text(original_actions, MagicMock())


def test_gate_plain_text_in_agent_mode_parses_valid_edit_block():
    executor = _make_mock_executor(mode="agent", delimiter_token="TOKEN")
    
    valid_edit_block = (
        "EDIT_FILE\n"
        "path: app.py\n"
        "command: replace_range\n"
        "start_line: 1\n"
        "end_line: 2\n"
        "RAW_LINES TOKEN\n"
        "print('hello')\n"
        "END_RAW_LINES TOKEN"
    )
    original_actions = [MessageAction(content=valid_edit_block)]
    
    gated_actions = executor._gate_agent_mode_plain_text(original_actions, MagicMock())
    
    assert len(gated_actions) == 1
    action = gated_actions[0]
    assert isinstance(action, FileEditAction)
    assert action.path == "app.py"
    assert action.command == "edit"
    assert action.new_str == "print('hello')"
