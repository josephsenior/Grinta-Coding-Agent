"""Unit tests for backend.cli.orient_tools."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.cli.orient_tools import (
    OrientLineModel,
    _count_collection,
    _fetch_target,
    _json_payload,
    _library_target,
    _payload_failed,
    _quote,
    analyze_observation_model,
    analyze_result,
    file_read_action_model,
    find_symbols_observation_model,
    glob_observation_model,
    grep_observation_model,
    grep_result,
    lsp_observation_model,
    lsp_result,
    mcp_action_model,
    mcp_observation_model,
    mcp_result,
    read_line_range_from_action,
    read_symbols_observation_model,
    read_symbols_result,
)


def test_orient_line_model_with_result_strips_and_defaults() -> None:
    model = OrientLineModel(
        tool='grep',
        icon='⌕',
        verb='Grepped',
        target='x',
        result='…',
    )
    updated = model.with_result('  done  ')
    assert updated.result == 'done'
    assert model.with_result('').result == 'completed'


def test_quote_and_plural_helpers() -> None:
    assert _quote('hello') == '"hello"'
    assert _quote('') == '""'
    assert grep_result(match_count=1, file_count=0, output_mode='count') == '1 match'
    assert grep_result(match_count=2, file_count=0, output_mode='count') == '2 matchs'


@pytest.mark.parametrize(
    ('payload', 'expected'),
    [
        ('{"results": [1, 2]}', 2),
        ('{"items": []}', 0),
        ('{"total_count": 5}', 5),
        ('plain text', None),
        ('', None),
    ],
)
def test_json_payload_and_count_collection(payload: str, expected: int | None) -> None:
    parsed = _json_payload(payload)
    if payload.startswith('{'):
        assert isinstance(parsed, dict)
    assert _count_collection(parsed) == expected


def test_payload_failed_detects_error_shapes() -> None:
    assert _payload_failed({'error': 'boom'}) is True
    assert _payload_failed({'isError': True}) is True
    assert _payload_failed({'ok': False}) is True
    assert _payload_failed({'results': []}) is False


@pytest.mark.parametrize(
    ('mode', 'match_count', 'file_count', 'error', 'expected'),
    [
        ('files_with_matches', 0, 3, '', '3 files'),
        ('files_with_matches', 0, 1, '', '1 file'),
        ('files_with_matches', 0, 0, '', 'no matches'),
        ('count', 4, 0, '', '4 matchs'),
        ('content', 2, 1, '', '2 matchs · 1 file'),
        ('content', 0, 0, '', 'no matches'),
        ('', 0, 2, '', '2 files'),
        ('', 0, 0, 'fail', 'failed'),
    ],
)
def test_grep_result_modes(
    mode: str,
    match_count: int,
    file_count: int,
    error: str,
    expected: str,
) -> None:
    assert (
        grep_result(
            match_count=match_count,
            file_count=file_count,
            output_mode=mode,
            error=error,
        )
        == expected
    )


def test_grep_observation_model_uses_observation_fields() -> None:
    obs = SimpleNamespace(
        pattern='foo',
        path='src',
        match_count=2,
        file_count=1,
        output_mode='content',
        error='',
    )
    model = grep_observation_model(obs)
    assert model.tool == 'grep'
    assert model.result == '2 matchs · 1 file'


def test_glob_observation_model_counts_files_and_errors() -> None:
    ok = glob_observation_model(SimpleNamespace(pattern='*.py', path='.', file_count=2))
    assert ok.result == '2 files'
    empty = glob_observation_model(
        SimpleNamespace(pattern='*.py', path='.', file_count=0, files=[], error='')
    )
    assert empty.result == 'no files'
    failed = glob_observation_model(
        SimpleNamespace(pattern='*.py', path='.', file_count=0, error='disk')
    )
    assert failed.result == 'failed'


def test_find_symbols_observation_model_multi_file() -> None:
    obs = SimpleNamespace(
        query='Foo',
        path='.',
        candidates=[
            {'path': 'a.py'},
            {'path': 'b.py'},
        ],
        error='',
    )
    model = find_symbols_observation_model(obs)
    assert model.result == '2 symbols · 2 files'


def test_read_line_range_from_action_variants() -> None:
    default = SimpleNamespace(view_range=None, start=0, end=-1)
    assert read_line_range_from_action(default) == 'lines 1–EOF'
    ranged = SimpleNamespace(view_range=[10, 20], start=0, end=-1)
    assert read_line_range_from_action(ranged) == 'lines 10–20'
    partial = SimpleNamespace(view_range=None, start=5, end=12)
    assert read_line_range_from_action(partial) == 'lines 5–12'


def test_file_read_action_model_includes_symbol() -> None:
    action = SimpleNamespace(
        path='backend/auth.py',
        qualified_name='AuthService',
        symbol_name='',
        symbol='',
        view_range=None,
        start=0,
        end=-1,
    )
    model = file_read_action_model(action)
    assert 'auth.py' in model.target
    assert 'AuthService' in model.target


@pytest.mark.parametrize(
    ('results', 'error', 'expected'),
    [
        ([], '', 'no symbols'),
        ([{'status': 'resolved'}], '', '1 resolved'),
        ([{'status': 'resolved'}, {'status': 'ambiguous'}], '', '1 resolved, 1 ambiguous'),
        ([{'status': 'not_found'}], 'boom', 'failed'),
    ],
)
def test_read_symbols_result(results: list[dict[str, str]], error: str, expected: str) -> None:
    assert read_symbols_result(results, error=error) == expected


def test_read_symbols_observation_model() -> None:
    obs = SimpleNamespace(
        path='pkg/mod.py',
        results=[{'status': 'resolved'}],
        error='',
        targets=[],
    )
    model = read_symbols_observation_model(obs)
    assert model.result == '1 resolved'


@pytest.mark.parametrize(
    ('command', 'content', 'available', 'expected'),
    [
        ('hover', '{}', True, 'completed'),
        ('diagnostics', '{"diagnostics": []}', True, 'clean'),
        ('diagnostics', '{"issues": [1, 2]}', True, '2 issues'),
        ('list_symbols', '{"symbols": ["a"]}', True, '1 symbol'),
        ('find_definition', '{"definitions": [1, 2, 3]}', True, '3 results'),
        ('find_references', 'line1\nline2', True, '2 results'),
        ('anything', '', False, 'unavailable'),
        ('anything', '', True, 'no output'),
    ],
)
def test_lsp_result(
    command: str, content: str, available: bool, expected: str
) -> None:
    assert lsp_result(command=command, content=content, available=available) == expected


def test_lsp_observation_model_reuses_pending_target() -> None:
    pending = OrientLineModel(
        tool='lsp',
        icon='≡',
        verb='Analyzed',
        target='hover · Auth',
        result='…',
    )
    obs = SimpleNamespace(content='{"hover": true}', available=True)
    model = lsp_observation_model(obs, pending)
    assert model.result == 'completed'


@pytest.mark.parametrize(
    ('command', 'content', 'error', 'expected'),
    [
        ('callers', '{"callers": [1, 2]}', '', '2 callers'),
        ('dependencies', '{"deps": [1]}', '', '1 deps'),
        ('tree', 'outline', '', 'completed'),
        ('semantic_search', 'hits', '', 'completed'),
        ('tree', '', '', 'no output'),
        ('tree', 'x', 'fail', 'failed'),
    ],
)
def test_analyze_result(command: str, content: str, error: str, expected: str) -> None:
    assert analyze_result(command=command, content=content, error=error) == expected


def test_analyze_observation_model() -> None:
    obs = SimpleNamespace(command='callers', path='.', content='{"callers": [1]}', error='')
    model = analyze_observation_model(obs)
    assert model.result == '1 caller'


@pytest.mark.parametrize(
    ('name', 'args', 'tool'),
    [
        ('web_search_exa', {'query': 'pytest'}, 'web_search'),
        ('web_fetch_exa', {'urls': ['https://example.com/docs']}, 'web_fetch'),
        ('resolve-library-id', {'libraryName': 'react', 'query': 'hooks'}, 'docs_resolve'),
        ('query-docs', {'library_id': '/react', 'query': 'state'}, 'docs_query'),
    ],
)
def test_mcp_action_model_known_tools(name: str, args: dict, tool: str) -> None:
    action = SimpleNamespace(name=name, arguments=args)
    model = mcp_action_model(action)
    assert model is not None
    assert model.tool == tool


def test_mcp_action_model_unknown_tool_returns_none() -> None:
    assert mcp_action_model(SimpleNamespace(name='other', arguments={})) is None


def test_mcp_result_and_observation_model() -> None:
    assert mcp_result('web_search', '{"results": [1, 2]}') == '2 results'
    assert mcp_result('web_search', '{"error": "x"}') == 'failed'
    pending = mcp_action_model(
        SimpleNamespace(name='web_search_exa', arguments={'query': 'docs'})
    )
    obs = SimpleNamespace(name='web_search_exa', content='{"items": [1]}')
    model = mcp_observation_model(obs, pending)
    assert model is not None
    assert model.result == '1 result'


def test_library_and_fetch_target_helpers() -> None:
    assert _library_target('react', 'hooks') == 'react · "hooks"'
    assert _library_target('', 'only-query') == '"only-query"'
    assert _fetch_target({}) == 'web'
    assert _fetch_target({'url': 'https://docs.python.org/3/library/os.html'}).startswith(
        'docs.python.org'
    )


def test_count_result_lines_and_json_helpers() -> None:
    from backend.cli.orient_tools import (
        _count_result_lines,
        _extract_json_list_count,
        _file_count_from_candidates,
    )

    assert _count_result_lines('a\n\nb\n') == 2
    assert _extract_json_list_count({'items': [1, 2]}, 'items') == 2
    assert _extract_json_list_count('plain', 'items') is None
    assert _file_count_from_candidates(
        [{'path': 'a.py'}, {'path': 'b.py'}, {'path': 'a.py'}]
    ) == 2
