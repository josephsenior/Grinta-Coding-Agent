import json

from unittest.mock import patch

from backend.engine.tools.lsp_query import create_lsp_query_tool
from backend.ledger.action.code_nav import LspQueryAction
from backend.utils.lsp.lsp_client import (
    LspClient,
)


def test_create_lsp_query_tool():
    """Verify the LSP query tool schema is correct."""
    tool = create_lsp_query_tool()

    assert tool['type'] == 'function'
    assert tool['function']['name'] == 'lsp'

    props = tool['function']['parameters']['properties']
    assert 'command' in props
    assert 'file' in props
    assert 'line' in props
    assert 'column' in props
    assert 'symbol' in props

    required = tool['function']['parameters']['required']
    assert 'command' in required
    assert 'file' in required


def test_lsp_query_action_creation():
    """Verify action dataclass parameters."""
    action = LspQueryAction(
        command='find_definition',
        file='/home/user/project/main.py',
        line=10,
        column=5,
    )

    assert action.action == 'lsp_query'
    assert action.command == 'find_definition'
    assert action.file == '/home/user/project/main.py'
    assert action.line == 10
    assert action.column == 5
    assert action.symbol == ''


def test_lsp_query_action_list_symbols():
    """Verify action dataclass handles list_symbols command."""
    action = LspQueryAction(
        command='list_symbols', file='/home/user/project/main.py', symbol='MyClass'
    )
    assert action.command == 'list_symbols'
    assert action.symbol == 'MyClass'
    assert action.line == 1


def test_lsp_client_graceful_degradation(monkeypatch, tmp_path):
    """Verify the LSP client reports unavailable when no server is configured."""
    py_file = tmp_path / 'file.py'
    py_file.write_text('x = 1\n', encoding='utf-8')

    client = LspClient()
    with patch('backend.utils.lsp.lsp_client.lsp_context_for_file', return_value=None):
        res = client.query('find_definition', str(py_file), 1, 1)
        assert not res.available
        assert 'No language server available' in res.error
        hover = client.query('hover', str(py_file), 1, 1)
        assert not hover.available
        symbols = client.query('list_symbols', str(py_file))
        assert not symbols.available
        assert symbols.symbols == []


def test_lsp_client_parse_content_length_framing() -> None:
    client = LspClient()
    msg = {'jsonrpc': '2.0', 'id': 1, 'result': {'capabilities': {}}}
    raw = json.dumps(msg)
    blob = f'Content-Length: {len(raw)}\r\n\r\n{raw}'
    parsed = client._parse_lsp_responses(blob)
    assert len(parsed) == 1
    assert parsed[0]['id'] == 1


def test_lsp_client_parse_multiple_messages() -> None:
    client = LspClient()
    a = json.dumps({'jsonrpc': '2.0', 'id': 1, 'result': 1})
    b = json.dumps({'jsonrpc': '2.0', 'id': 2, 'result': 2})
    blob = f'Content-Length: {len(a)}\r\n\r\n{a}Content-Length: {len(b)}\r\n\r\n{b}'
    parsed = client._parse_lsp_responses(blob)
    assert [x['id'] for x in parsed] == [1, 2]
