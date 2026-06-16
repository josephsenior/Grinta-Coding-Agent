"""Additional unit tests for orient_tools helpers."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.cli.orient_tools import (
    OrientLineModel,
    _command_from_target,
    _display_path,
    _fetch_target,
    _library_target,
    _quote,
    analyze_action_model,
    analyze_result,
    file_read_action_model,
    find_symbols_action_model,
    glob_action_model,
    grep_action_model,
    lsp_action_model,
    lsp_result,
    mcp_action_model,
    mcp_result,
    read_symbols_action_model,
    read_symbols_result,
)


def test_quote_and_display_path() -> None:
    assert _quote('needle') == '"needle"'
    assert len(_display_path('backend/very/long/path/to/module.py')) <= 44


def test_grep_and_glob_action_models() -> None:
    grep = grep_action_model(SimpleNamespace(pattern='foo', path='src'))
    assert grep.tool == 'grep'
    assert 'foo' in grep.target
    glob = glob_action_model(SimpleNamespace(pattern='*.py', path='.'))
    assert glob.tool == 'glob'


def test_find_and_read_symbols_action_models() -> None:
    find = find_symbols_action_model(
        SimpleNamespace(query='Auth', path='backend', candidates=[])
    )
    assert find.tool == 'find_symbols'
    read = read_symbols_action_model(
        SimpleNamespace(path='pkg/mod.py', targets=['Foo', 'Bar'])
    )
    assert 'symbol' in read.target


def test_file_read_action_model_line_ranges() -> None:
    action = SimpleNamespace(
        path='main.py',
        qualified_name='',
        symbol_name='',
        symbol='',
        view_range=[5, 10],
        start=0,
        end=-1,
    )
    model = file_read_action_model(action)
    assert model.result == 'lines 5–10'


def test_lsp_action_and_result_variants() -> None:
    action = lsp_action_model(
        SimpleNamespace(command='hover', symbol='Foo', file='a.py')
    )
    assert action.tool == 'lsp'
    assert _command_from_target('hover · Foo') == 'hover'
    assert lsp_result(command='diagnostics', content='{"issues": [1]}') == '1 issue'


def test_analyze_action_and_result() -> None:
    action = analyze_action_model(SimpleNamespace(command='tree', path='.'))
    assert action.tool == 'analyze_project_structure'
    assert (
        analyze_result(command='imports', content='import os\nimport sys')
        == 'completed'
    )


@pytest.mark.parametrize(
    ('tool', 'content', 'expected'),
    [
        ('web_search', '{"results": []}', '0 results'),
        ('web_search', '{"error": "x"}', 'failed'),
        ('web_search', 'plain', 'results'),
    ],
)
def test_mcp_result_variants(tool: str, content: str, expected: str) -> None:
    assert mcp_result(tool, content) == expected


def test_mcp_action_models_for_docs_and_fetch() -> None:
    docs = mcp_action_model(
        SimpleNamespace(
            name='query-docs',
            arguments={'library_id': '/react', 'query': 'hooks'},
        )
    )
    assert docs is not None
    assert docs.tool == 'docs_query'
    fetch = mcp_action_model(
        SimpleNamespace(name='fetch', arguments={'url': 'https://example.com/a/b'})
    )
    assert fetch is not None
    assert fetch.tool == 'web_fetch'


def test_library_and_fetch_target_edge_cases() -> None:
    assert _library_target('react', '') == 'react'
    assert _fetch_target({'urls': ['https://a.com', 'https://b.com']}).startswith(
        'a.com'
    )


def test_read_symbols_result_mixed_statuses() -> None:
    results = [
        {'status': 'resolved'},
        {'status': 'ambiguous'},
        {'status': 'not_found'},
        {'status': 'unknown'},
    ]
    text = read_symbols_result(results)
    assert 'resolved' in text
    assert 'ambiguous' in text
    assert 'not found' in text
    assert 'unknown' in text


def test_orient_line_with_result_on_mcp_models() -> None:
    pending = OrientLineModel(
        tool='web_fetch',
        icon='⚐',
        verb='Fetched',
        target='example.com',
        result='…',
        area='web',
    )
    updated = pending.with_result('3 results')
    assert updated.result == '3 results'
