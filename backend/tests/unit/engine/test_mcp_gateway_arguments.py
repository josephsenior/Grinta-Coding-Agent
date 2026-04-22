"""Tests for ``call_mcp_tool`` gateway argument merging (Context7 and similar)."""

from __future__ import annotations

from backend.engine.function_calling import _handle_execute_mcp_tool_tool


def test_gateway_hoists_top_level_keys_into_arguments() -> None:
    action = _handle_execute_mcp_tool_tool(
        {
            'tool_name': 'resolve-library-id',
            'libraryName': 'React',
            'query': 'useEffect hook usage',
        }
    )
    assert action.name == 'resolve-library-id'
    assert action.arguments == {
        'libraryName': 'React',
        'query': 'useEffect hook usage',
    }


def test_gateway_merges_partial_inner_with_top_level() -> None:
    action = _handle_execute_mcp_tool_tool(
        {
            'tool_name': 'resolve-library-id',
            'arguments': {'query': 'hooks'},
            'libraryName': 'React',
        }
    )
    assert action.arguments == {'query': 'hooks', 'libraryName': 'React'}


def test_gateway_inner_wins_non_empty_over_top_level() -> None:
    action = _handle_execute_mcp_tool_tool(
        {
            'tool_name': 'resolve-library-id',
            'arguments': {'libraryName': 'Inner', 'query': 'q1'},
            'libraryName': 'Outer',
        }
    )
    assert action.arguments['libraryName'] == 'Inner'
    assert action.arguments['query'] == 'q1'


def test_context7_resolve_fills_missing_query_when_library_name_present() -> None:
    action = _handle_execute_mcp_tool_tool(
        {
            'tool_name': 'resolve-library-id',
            'arguments': {'libraryName': 'react'},
        }
    )
    assert action.arguments['libraryName'] == 'react'
    assert 'query' in action.arguments
    assert 'react' in action.arguments['query'].lower()


def test_query_docs_passes_through_merged_args() -> None:
    action = _handle_execute_mcp_tool_tool(
        {
            'tool_name': 'query-docs',
            'libraryId': '/facebook/react',
            'query': 'useEffect',
        }
    )
    assert action.arguments == {'libraryId': '/facebook/react', 'query': 'useEffect'}
