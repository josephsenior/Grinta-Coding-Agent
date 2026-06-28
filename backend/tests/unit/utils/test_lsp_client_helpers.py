"""Focused tests for lsp_client helpers and LspResult formatting."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from backend.utils.lsp import lsp_client as lc


def test_detect_any_lsp_server_true() -> None:
    with patch(
        'backend.utils.runtime_detect.has_any_lsp_server',
        return_value=True,
    ):
        assert lc._detect_any_lsp_server() is True


def test_detect_any_lsp_server_false_on_import_error() -> None:
    with patch(
        'backend.utils.runtime_detect.has_any_lsp_server',
        side_effect=RuntimeError('boom'),
    ):
        assert lc._detect_any_lsp_server() is False


def test_lsp_location_and_symbol_str() -> None:
    loc = lc.LspLocation(file='/a/b.py', line=2, column=3)
    assert str(loc).endswith('b.py:2:3')
    sym = lc.LspSymbol(name='foo', kind='Function', line=10)
    assert 'foo' in str(sym) and '10' in str(sym)


def test_lsp_code_action_str_variants() -> None:
    plain = lc.LspCodeAction(title='Fix', kind='quickfix')
    assert 'Fix' in str(plain)
    pref = lc.LspCodeAction(
        title='Organize',
        kind='source.organizeImports',
        is_preferred=True,
        diagnostic_message='unused import',
    )
    out = str(pref)
    assert '★' in out and 'unused import' in out


def test_lsp_result_format_text_branches() -> None:
    assert 'not available' in lc.LspResult(available=False).format_text('any')
    assert (
        lc.LspResult(error='e').format_text('find_definition').startswith('LSP error')
    )
    assert 'No results' in lc.LspResult().format_text('find_definition')
    loc = lc.LspLocation(file='f.py', line=1, column=1)
    body = lc.LspResult(locations=[loc]).format_text('find_definition')
    assert 'Found 1 result' in body
    assert lc.LspResult(hover_text='hi').format_text('hover') == 'hi'
    assert 'No hover' in lc.LspResult().format_text('hover')
    sym = lc.LspSymbol(name='s', kind='Class', line=1)
    sy = lc.LspResult(symbols=[sym]).format_text('list_symbols')
    assert 'Symbols in file' in sy
    diag = lc.LspResult(locations=[loc]).format_text('diagnostics')
    assert 'Diagnostics' in diag
    clean = lc.LspResult().format_text('diagnostics')
    assert 'clean' in clean
    act = lc.LspCodeAction(title='x')
    ca = lc.LspResult(code_actions=[act]).format_text('code_action')
    assert 'code actions' in ca.lower()
    fallback = lc.LspResult().format_text('unknown_cmd_xyz')
    assert isinstance(fallback, str)


def test_lsp_query_diagnostics_accepts_process_timeout(tmp_path: Path) -> None:
    py_file = tmp_path / 'x.py'
    py_file.write_text('x = 1\n', encoding='utf-8')
    client = lc.LspClient()
    with (
        patch.object(client, '_run_query', return_value=lc.LspResult()) as run_query,
        patch.object(
            client,
            '_get_server_command',
            return_value=['python', '-m', 'pylsp'],
        ),
    ):
        client.query('diagnostics', str(py_file), process_timeout=0.25)
    run_query.assert_called_once_with(
        'diagnostics',
        str(py_file),
        1,
        1,
        '',
        process_timeout=0.25,
        post_edit=False,
    )


def test_get_server_command_returns_none_when_not_detected(tmp_path: Path) -> None:
    py_file = tmp_path / 'x.py'
    py_file.write_text('x', encoding='utf-8')
    client = lc.LspClient()
    with patch(
        'backend.utils.lsp.lsp_client.lsp_context_for_file',
        return_value=None,
    ):
        cmd = client._get_server_command(str(py_file))  # noqa: SLF001
    assert cmd is None


def test_detect_pylsp_cached_skips_detect() -> None:
    lc._PYLSP_AVAILABLE = True  # noqa: SLF001
    try:
        with patch(
            'backend.utils.runtime_detect.detect_lsp_servers',
            side_effect=AssertionError('should not run'),
        ):
            assert lc._detect_pylsp() is True
    finally:
        lc._PYLSP_AVAILABLE = None  # noqa: SLF001


def test_detect_pylsp_uncached_empty_servers() -> None:
    lc._PYLSP_AVAILABLE = None  # noqa: SLF001
    try:
        with patch(
            'backend.utils.runtime_detect.lsp_command_for_file',
            return_value=None,
        ):
            assert lc._detect_pylsp() is False
    finally:
        lc._PYLSP_AVAILABLE = None  # noqa: SLF001


def test_parse_document_symbols_hierarchical() -> None:
    client = lc.LspClient()
    payload = [
        {
            'name': 'Outer',
            'kind': 5,
            'range': {'start': {'line': 0, 'character': 0}, 'end': {'line': 2, 'character': 0}},
            'children': [
                {
                    'name': 'inner',
                    'kind': 12,
                    'range': {
                        'start': {'line': 1, 'character': 4},
                        'end': {'line': 1, 'character': 10},
                    },
                }
            ],
        }
    ]
    symbols = client._parse_document_symbols(payload, '')  # noqa: SLF001
    assert [s.name for s in symbols] == ['Outer', 'inner']


def test_build_init_msgs_uses_workspace_and_language_id(tmp_path: Path) -> None:
    (tmp_path / 'pyproject.toml').write_text('[project]\nname="x"\n', encoding='utf-8')
    src = tmp_path / 'pkg' / 'mod.py'
    src.parent.mkdir()
    src.write_text('def ok():\n    pass\n', encoding='utf-8')
    ctx = lc.LspFileContext(
        server_name='pyright-langserver',
        command=('pyright-langserver', '--stdio'),
        language_id='python',
        workspace_root=tmp_path,
    )
    client = lc.LspClient()
    with patch.object(client, '_get_context', return_value=ctx):
        msgs = client._build_init_msgs(src.as_uri(), str(src), 'def ok():\n    pass\n')
    init = msgs[0]['params']
    assert init['rootUri'] == tmp_path.as_uri()
    assert init['workspaceFolders'][0]['uri'] == tmp_path.as_uri()
    assert msgs[2]['params']['textDocument']['languageId'] == 'python'


# --- Patch 1: JSON-RPC error response surfacing ---


def test_error_from_response_extracts_message_and_code() -> None:
    client = lc.LspClient()
    err = client._error_from_response(  # noqa: SLF001
        {'jsonrpc': '2.0', 'id': 5, 'error': {'code': -32601, 'message': 'method not found'}}
    )
    assert err is not None
    assert 'method not found' in err
    assert '-32601' in err


def test_error_from_response_none_for_success() -> None:
    client = lc.LspClient()
    assert (
        client._error_from_response(  # noqa: SLF001
            {'jsonrpc': '2.0', 'id': 5, 'result': None}
        )
        is None
    )


def test_error_result_surfaces_message() -> None:
    client = lc.LspClient()
    result = client._error_result(  # noqa: SLF001
        {'jsonrpc': '2.0', 'id': 5, 'error': {'code': -1, 'message': 'denied'}},
        hint='hover',
    )
    assert not result.available
    assert 'denied' in result.error
    assert 'hover' in result.error


def test_error_result_no_result_member() -> None:
    """A response with neither result nor error is surfaced as an error."""
    client = lc.LspClient()
    result = client._error_result(  # noqa: SLF001
        {'jsonrpc': '2.0', 'id': 5}, hint='symbols'
    )
    assert not result.available
    assert 'no result' in result.error


def test_snippet_from_stderr_extracts_tail() -> None:
    assert lc._snippet_from_stderr('') == ''
    assert lc._snippet_from_stderr('   ') == ''
    long = 'x' * 600
    snippet = lc._snippet_from_stderr(long)
    assert len(snippet) == 500
    assert snippet == long[-500:]


def test_lsp_query_surfaces_jsonrpc_error_in_session_path(tmp_path: Path) -> None:
    """A JSON-RPC error from the session must be surfaced, not swallowed."""
    py_file = tmp_path / 'f.py'
    py_file.write_text('x = 1\n', encoding='utf-8')
    ctx = lc.LspFileContext(
        server_name='pyright-langserver',
        command=('pyright-langserver', '--stdio'),
        language_id='python',
        workspace_root=tmp_path,
    )
    client = lc.LspClient()
    fake_session = MagicMock()
    fake_session.supports.return_value = True
    fake_session.prepare_document.return_value = True
    fake_session.request.return_value = {
        'jsonrpc': '2.0',
        'id': 2,
        'error': {'code': -32601, 'message': 'method not supported'},
    }
    with (
        patch.object(client, '_get_context', return_value=ctx),
        patch.object(client, '_resolve_timeout', return_value=5.0),
        patch('backend.utils.lsp.lsp_client.get_lsp_session_pool') as pool_mock,
    ):
        pool_mock.return_value.get.return_value = fake_session
        result = client.query('hover', str(py_file), 1, 1)
    assert not result.available
    assert 'method not supported' in result.error


# --- Patch 2: capability gating ---


def test_lsp_query_capability_gate_blocks_unsupported(tmp_path: Path) -> None:
    """A session that doesn't advertise a capability returns a clear error."""
    py_file = tmp_path / 'f.py'
    py_file.write_text('x = 1\n', encoding='utf-8')
    ctx = lc.LspFileContext(
        server_name='pyright-langserver',
        command=('pyright-langserver', '--stdio'),
        language_id='python',
        workspace_root=tmp_path,
    )
    client = lc.LspClient()
    fake_session = MagicMock()
    fake_session.supports.return_value = False
    fake_session.prepare_document.return_value = True
    with (
        patch.object(client, '_get_context', return_value=ctx),
        patch.object(client, '_resolve_timeout', return_value=5.0),
        patch('backend.utils.lsp.lsp_client.get_lsp_session_pool') as pool_mock,
    ):
        pool_mock.return_value.get.return_value = fake_session
        result = client.query('code_action', str(py_file), 1, 1)
    assert not result.available
    assert 'does not advertise' in result.error
    assert 'codeAction' in result.error
    fake_session.request.assert_not_called()


def test_unsupported_result_includes_server_and_method() -> None:
    client = lc.LspClient()
    ctx = lc.LspFileContext(
        server_name='ruff',
        command=('ruff',),
        language_id='python',
        workspace_root=Path('.'),
    )
    result = client._unsupported_result(ctx, 'textDocument/hover')  # noqa: SLF001
    assert not result.available
    assert 'ruff' in result.error
    assert 'textDocument/hover' in result.error


# --- Patch 4: stderr surfacing in one-shot failures ---


def test_server_failed_includes_stderr() -> None:
    client = lc.LspClient()
    result = client._server_failed(stderr='boom: cannot find module')  # noqa: SLF001
    assert not result.available
    assert 'boom: cannot find module' in result.error
    assert 'Server stderr' in result.error
