"""Tests for native web_search / web_fetch tool wiring."""

from __future__ import annotations

import pytest

from backend.core.errors import FunctionCallValidationError
from backend.engine.tools._tool_handlers import (
    _handle_web_fetch_tool,
    _handle_web_search_tool,
)
from backend.engine.tools.web_tools import (
    EXA_WEB_SEARCH_MCP_TOOL,
    FALLBACK_FETCH_MCP_TOOL,
    NATIVE_WEB_FETCH_ROUTER,
    build_web_fetch_action,
    build_web_search_action,
    create_web_fetch_tool,
    create_web_search_tool,
    native_web_fetch_wrapper,
)
from backend.integrations.mcp.native_backends import MCP_TOOLS_HIDDEN_BY_NATIVE_WEB
from backend.ledger.action.mcp import MCPAction


def test_create_web_tool_schemas():
    assert create_web_search_tool()['function']['name'] == 'web_search'
    assert create_web_fetch_tool()['function']['name'] == 'web_fetch'


def test_build_web_search_action_maps_to_exa_mcp():
    action = build_web_search_action(
        {'query': 'pytest fixture patterns', 'num_results': 5}
    )
    assert isinstance(action, MCPAction)
    assert action.name == EXA_WEB_SEARCH_MCP_TOOL
    assert action.arguments == {'query': 'pytest fixture patterns', 'numResults': 5}


def test_build_web_fetch_action_uses_internal_router():
    action = build_web_fetch_action(
        {'urls': ['https://example.com/docs'], 'max_characters': 4000}
    )
    assert action.name == NATIVE_WEB_FETCH_ROUTER
    assert action.arguments['urls'] == ['https://example.com/docs']
    assert action.arguments['max_characters'] == 4000


def test_build_web_search_rejects_empty_query():
    with pytest.raises(FunctionCallValidationError):
        build_web_search_action({'query': '   '})


@pytest.mark.asyncio
async def test_native_web_fetch_wrapper_prefers_exa():
    calls: list[tuple[str, dict]] = []

    async def _call(tool_name: str, args: dict):
        calls.append((tool_name, args))
        return {'ok': True, 'content': [{'text': 'exa body'}]}

    result = await native_web_fetch_wrapper(
        [],
        {'urls': ['https://example.com'], 'max_characters': 1000},
        _call,
    )
    assert result['backend'] == 'exa'
    assert calls[0][0] == 'web_fetch_exa'


@pytest.mark.asyncio
async def test_native_web_fetch_wrapper_falls_back_to_fetch():
    calls: list[str] = []

    async def _call(tool_name: str, args: dict):
        calls.append(tool_name)
        if tool_name == 'web_fetch_exa':
            return {'ok': False, 'isError': True}
        return {'ok': True, 'content': [{'text': 'fetch body'}]}

    result = await native_web_fetch_wrapper(
        [],
        {'urls': ['https://example.com']},
        _call,
    )
    assert result['backend'] == 'fetch'
    assert calls == ['web_fetch_exa', FALLBACK_FETCH_MCP_TOOL]


def test_hidden_mcp_tool_names_include_exa_and_fetch():
    assert 'web_search_exa' in MCP_TOOLS_HIDDEN_BY_NATIVE_WEB
    assert 'web_fetch_exa' in MCP_TOOLS_HIDDEN_BY_NATIVE_WEB
    assert 'fetch' in MCP_TOOLS_HIDDEN_BY_NATIVE_WEB


def test_handlers_return_mcp_actions():
    search = _handle_web_search_tool({'query': 'rust async book'})
    fetch = _handle_web_fetch_tool({'urls': ['https://doc.rust-lang.org']})
    assert isinstance(search, MCPAction)
    assert isinstance(fetch, MCPAction)
