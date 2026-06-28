"""Focused tests for lsp_client helpers and LspResult formatting."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from backend.utils.lsp import lsp_client as lc
from backend.utils.lsp.lsp_project_routing import LspFileContext


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
