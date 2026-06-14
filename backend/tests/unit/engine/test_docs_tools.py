"""Tests for native docs_resolve / docs_query tool wiring."""

from __future__ import annotations

import pytest

from backend.core.errors import FunctionCallValidationError
from backend.engine.tools._tool_handlers import (
    _handle_docs_query_tool,
    _handle_docs_resolve_tool,
)
from backend.engine.tools.docs_tools import (
    build_docs_query_action,
    build_docs_resolve_action,
    create_docs_query_tool,
    create_docs_resolve_tool,
)
from backend.integrations.mcp.native_backends import (
    CONTEXT7_QUERY_MCP_TOOL,
    CONTEXT7_RESOLVE_MCP_TOOL,
    MCP_TOOLS_HIDDEN_BY_NATIVE_DOCS,
)
from backend.ledger.action.mcp import MCPAction


def test_create_docs_tool_schemas():
    assert create_docs_resolve_tool()['function']['name'] == 'docs_resolve'
    assert create_docs_query_tool()['function']['name'] == 'docs_query'


def test_build_docs_resolve_action_maps_to_context7():
    action = build_docs_resolve_action(
        {
            'library_name': 'React',
            'query': 'useEffect cleanup patterns',
        }
    )
    assert isinstance(action, MCPAction)
    assert action.name == CONTEXT7_RESOLVE_MCP_TOOL
    assert action.arguments['libraryName'] == 'React'
    assert action.arguments['query'] == 'useEffect cleanup patterns'


def test_build_docs_resolve_fills_query_when_missing():
    action = build_docs_resolve_action({'library_name': 'next.js'})
    assert 'query' in action.arguments
    assert 'next.js' in action.arguments['query'].lower()


def test_build_docs_query_action_maps_to_context7():
    action = build_docs_query_action(
        {
            'library_id': '/facebook/react',
            'query': 'useEffect',
        }
    )
    assert action.name == CONTEXT7_QUERY_MCP_TOOL
    assert action.arguments == {'libraryId': '/facebook/react', 'query': 'useEffect'}


def test_build_docs_resolve_rejects_empty_library_name():
    with pytest.raises(FunctionCallValidationError):
        build_docs_resolve_action({'library_name': '   ', 'query': 'hooks'})


def test_build_docs_query_rejects_missing_fields():
    with pytest.raises(FunctionCallValidationError):
        build_docs_query_action({'library_id': '/facebook/react'})
    with pytest.raises(FunctionCallValidationError):
        build_docs_query_action({'query': 'hooks'})


def test_hidden_mcp_tool_names_include_context7():
    assert CONTEXT7_RESOLVE_MCP_TOOL in MCP_TOOLS_HIDDEN_BY_NATIVE_DOCS
    assert CONTEXT7_QUERY_MCP_TOOL in MCP_TOOLS_HIDDEN_BY_NATIVE_DOCS


def test_handlers_return_mcp_actions():
    resolve = _handle_docs_resolve_tool(
        {'library_name': 'Prisma', 'query': 'migrate deploy'}
    )
    query = _handle_docs_query_tool(
        {'library_id': '/prisma/docs', 'query': 'schema push'}
    )
    assert isinstance(resolve, MCPAction)
    assert isinstance(query, MCPAction)
