import pytest
from unittest.mock import MagicMock

from backend.engines.orchestrator.tools.lsp_query import create_lsp_query_tool
from backend.engines.orchestrator.tools.lsp_client import (
    LspClient,
    LspResult,
)
from backend.events.action.code_nav import LspQueryAction


def test_create_lsp_query_tool():
    """Verify the LSP query tool schema is correct."""
    tool = create_lsp_query_tool()

    assert tool["type"] == "function"
    assert tool["function"]["name"] == "lsp_query"

    props = tool["function"]["parameters"]["properties"]
    assert "command" in props
    assert "file" in props
    assert "line" in props
    assert "column" in props
    assert "symbol" in props

    required = tool["function"]["parameters"]["required"]
    assert "command" in required
    assert "file" in required


def test_lsp_query_action_creation():
    """Verify action dataclass parameters."""
    action = LspQueryAction(
        command="find_definition",
        file="/home/user/project/main.py",
        line=10,
        column=5,
    )

    assert action.action == "lsp_query"
    assert action.command == "find_definition"
    assert action.file == "/home/user/project/main.py"
    assert action.line == 10
    assert action.column == 5
    assert action.symbol == ""


def test_lsp_query_action_list_symbols():
    """Verify action dataclass handles list_symbols command."""
    action = LspQueryAction(
        command="list_symbols", file="/home/user/project/main.py", symbol="MyClass"
    )
    assert action.command == "list_symbols"
    assert action.symbol == "MyClass"
    assert action.line == 1


def test_lsp_client_graceful_degradation(monkeypatch):
    """Verify the LSP client gracefully fails when pylsp is not available."""

    # Mock subprocess.Popen to raise FileNotFoundError (command not found)
    def mock_popen(*args, **kwargs):
        raise FileNotFoundError("pylsp not found")

    monkeypatch.setattr("subprocess.Popen", mock_popen)

    client = LspClient()

    # All commands should return empty/degraded results safely
    assert client.query("find_definition", "file.py", 1, 1).locations == []
    assert client.query("find_references", "file.py", 1, 1).locations == []
    # hover returns LspResult with available=False when pylsp is not installed
    res = client.query("hover", "file.py", 1, 1)
    assert not res.available
    assert "LSP is not available" in res.format_text("hover")
    assert client.query("list_symbols", "file.py").symbols == []
