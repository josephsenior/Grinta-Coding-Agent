"""Unit tests for pure helpers in backend.integrations.mcp.mcp_utils."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.config.mcp_config import MCPConfig, MCPServerConfig
from backend.integrations.mcp import mcp_utils as mu
from backend.integrations.mcp.mcp_bootstrap_status import (
    get_mcp_bootstrap_status,
    reset_mcp_bootstrap_status,
)


def test_get_mcp_connect_timeout_sec_invalid_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('APP_MCP_CONNECT_TIMEOUT_SEC', 'not-a-float')
    assert mu._get_mcp_connect_timeout_sec() == 60.0
    monkeypatch.setenv('APP_MCP_CONNECT_TIMEOUT_SEC', '-1')
    assert mu._get_mcp_connect_timeout_sec() == 60.0


def test_resolve_server_env_none_empty_and_literals() -> None:
    assert mu._resolve_server_env(None) is None
    assert mu._resolve_server_env({}) == {}
    assert mu._resolve_server_env({'X': 123}) == {'X': '123'}


def test_resolve_server_env_empty_string_uses_os(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('TOKEN', 'secret')
    out = mu._resolve_server_env({'TOKEN': ''})
    assert out == {'TOKEN': 'secret'}


def test_resolve_server_env_dollar_var() -> None:
    with patch.dict('os.environ', {'MY_TOKEN': 'abc'}, clear=False):
        out = mu._resolve_server_env({'AUTH': '${MY_TOKEN}'})
    assert out == {'AUTH': 'abc'}


def test_apply_exa_mcp_url_auth_adds_key() -> None:
    s = MCPServerConfig(
        name='exa',
        type='sse',
        url='https://mcp.exa.ai/mcp',
        api_key='sekret',
    )
    out = mu._apply_exa_mcp_url_auth(s)
    assert 'exaApiKey=' in (out.url or '')
    assert out.api_key is None


def test_apply_exa_mcp_url_auth_noop_when_not_exa() -> None:
    s = MCPServerConfig(name='x', type='sse', url='https://other.example/mcp')
    assert mu._apply_exa_mcp_url_auth(s).url == 'https://other.example/mcp'


def test_convert_mcps_to_tools_none_and_empty() -> None:
    assert mu.convert_mcps_to_tools(None) == []
    assert mu.convert_mcps_to_tools([]) == []


def test_convert_mcps_to_tools_with_mock_tools() -> None:
    tool = MagicMock()
    tool.name = 't1'
    tool.to_param.return_value = {'type': 'function', 'function': {'name': 't1'}}
    client = MagicMock()
    client.tools = [tool]
    out = mu.convert_mcps_to_tools([client])
    assert len(out) >= 1


def test_resolve_mcp_bootstrap_state() -> None:
    assert mu._resolve_mcp_bootstrap_state(0, []) == 'connected_no_remote_tools'
    assert mu._resolve_mcp_bootstrap_state(3, ['e']) == 'partial_tool_conversion'
    assert mu._resolve_mcp_bootstrap_state(3, []) == 'healthy'


def test_set_mcp_bootstrap_records_status() -> None:
    reset_mcp_bootstrap_status()
    mu._set_mcp_bootstrap(
        state='healthy',
        mcp_enabled=True,
        configured_server_count=1,
        attempted_server_count=1,
        connected_client_count=1,
        remote_tool_param_count=2,
        conversion_errors=[],
    )
    d = get_mcp_bootstrap_status()
    assert d['state'] == 'healthy'
    assert d['remote_tool_param_count'] == 2
    reset_mcp_bootstrap_status()


def test_serialize_normalize_error_helpers() -> None:
    assert '"a"' in mu._serialize_result_to_json({'a': 1})
    norm = mu._normalize_mcp_success_payload({'isError': False})
    assert norm['ok'] is True
    err_pl = mu._build_mcp_error_payload(
        action_name='x',
        message='bad',
        code='E1',
        retryable=True,
        category='bad_args',
    )
    assert err_pl['ok'] is False and err_pl['retryable'] is True
    assert err_pl['category'] == 'bad_args'


def test_make_mcp_observation_propagates_category() -> None:
    action = SimpleNamespace(name='x', arguments={}, action='call_mcp_tool')
    payload = mu._build_mcp_error_payload(
        action_name='x',
        message='nope',
        code='MCP_TOOL_TIMEOUT',
        retryable=True,
        category='timeout',
    )
    obs = mu._make_mcp_observation(action, payload)  # type: ignore[arg-type]
    assert obs.tool_result['category'] == 'timeout'
    assert obs.tool_result['ok'] is False
    assert obs.tool_result['retryable'] is True


def test_looks_like_mcp_validation_error() -> None:
    assert mu._looks_like_mcp_validation_error('-32602 invalid') is True
    assert mu._looks_like_mcp_validation_error('ok') is False


def test_coerce_helpers() -> None:
    assert mu._coerce_string_value('a') == ('a', False)
    v, ch = mu._coerce_string_value({'x': 1})
    assert ch is True and '"x"' in v
    assert mu._coerce_array_value((1, 2)) == ([1, 2], True)
    assert mu._coerce_object_value('{"a":1}') == ({'a': 1}, True)
    assert mu._coerce_integer_value('42') == (42, True)
    assert mu._coerce_number_value('3.5') == (3.5, True)
    assert mu._coerce_boolean_value('yes') == (True, True)


def test_coerce_value_to_schema_unknown_type() -> None:
    v, ch = mu._coerce_value_to_schema(1, {})
    assert ch is False and v == 1


def test_repair_args_with_schema() -> None:
    schema = {'type': 'object', 'properties': {'n': {'type': 'integer'}}}
    repaired, changed = mu._repair_args_with_schema({'n': '10'}, schema)
    assert changed is True
    assert repaired['n'] == 10


def test_extract_mcp_jsonrpc_error_code() -> None:
    assert mu._extract_mcp_jsonrpc_error_code('fail -32602 here') == '-32602'
    assert mu._extract_mcp_jsonrpc_error_code('no code') is None


@pytest.mark.asyncio
async def test_create_mcps_empty() -> None:
    assert await mu.create_mcps([]) == []


@pytest.mark.asyncio
async def test_connect_to_server_unknown_type() -> None:
    bad = SimpleNamespace(type='unknown')
    out = await mu._connect_to_server(bad, None)  # type: ignore[arg-type]
    assert out is None


@pytest.mark.asyncio
async def test_disconnect_probe_mcps_empty() -> None:
    await mu._disconnect_probe_mcps([])


@pytest.mark.asyncio
async def test_disconnect_probe_mcps_calls_disconnect() -> None:
    c = MagicMock()
    c.disconnect = AsyncMock()
    await mu._disconnect_probe_mcps([c])
    c.disconnect.assert_awaited_once()


def test_prepare_connected_mcp_tools_updates_bootstrap() -> None:
    reset_mcp_bootstrap_status()
    tool = SimpleNamespace(
        name='remote_tool',
        description='d',
        inputSchema={},
    )
    client = SimpleNamespace(
        tools=[tool],
        tool_map={},
        exposed_to_protocol={},
        register_alias_context=MagicMock(),
        _server_config=SimpleNamespace(name='srv'),
    )
    cfg = MCPConfig()
    mu._prepare_connected_mcp_tools(
        [client],  # type: ignore[list-item]
        cfg,
        frozenset(),
        configured_n=1,
        attempted_n=1,
    )
    st = get_mcp_bootstrap_status()
    assert st['connected_client_count'] == 1
    reset_mcp_bootstrap_status()
