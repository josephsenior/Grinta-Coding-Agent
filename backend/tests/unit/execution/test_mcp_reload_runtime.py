"""Unit tests for ``reload_mcp_servers`` in the shared runtime helper."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.config.mcp_config import MCPServerConfig
from backend.execution.utils import mcp_runtime
from backend.integrations.mcp import mcp_utils as mcp_utils_mod


def _server(name: str, *, type_: str = 'stdio', **kwargs: Any) -> MCPServerConfig:
    payload: dict[str, Any] = {'name': name, 'type': type_}
    if type_ == 'stdio':
        payload.setdefault('command', kwargs.get('command', 'echo'))
    else:
        payload.setdefault('url', kwargs.get('url', 'http://localhost:8000'))
    payload.update({k: v for k, v in kwargs.items() if k not in payload})
    return MCPServerConfig(**payload)


def _make_client(
    name: str, *, type_: str = 'stdio', disconnect_fail: bool = False
) -> Any:
    client = MagicMock()
    client._server_config = _server(name, type_=type_)
    if disconnect_fail:
        client.disconnect = AsyncMock(side_effect=RuntimeError('boom'))
    else:
        client.disconnect = AsyncMock(return_value=None)
    return client


@pytest.mark.asyncio
async def test_reload_no_changes_keeps_clients() -> None:
    existing = _make_client('github')
    s = _server('github')
    clients, servers, summary = await mcp_runtime.reload_mcp_servers(
        new_servers=[s],
        current_clients=[existing],
        current_servers_resolved=[s],
    )
    assert clients == [existing]
    assert servers == [s]
    assert summary['added'] == []
    assert summary['removed'] == []
    assert summary['reconnected'] == []


@pytest.mark.asyncio
async def test_reload_removes_orphan_client() -> None:
    existing = _make_client('old')
    s_new = _server('new')
    new_client = _make_client('new')
    with patch.object(
        mcp_utils_mod,
        'create_mcps',
        AsyncMock(return_value=[new_client]),
    ):
        clients, servers, summary = await mcp_runtime.reload_mcp_servers(
            new_servers=[s_new],
            current_clients=[existing],
            current_servers_resolved=[_server('old')],
        )
    existing.disconnect.assert_awaited_once()
    assert all(c is not existing for c in clients)
    assert servers == [s_new]
    assert summary['removed'] == ['old']
    assert summary['added'] == ['new']


@pytest.mark.asyncio
async def test_reload_adds_new_server() -> None:
    existing = _make_client('a')
    s_a = _server('a')
    s_b = _server('b')
    new_client = _make_client('b')
    with patch.object(
        mcp_utils_mod,
        'create_mcps',
        AsyncMock(return_value=[new_client]),
    ) as create:
        clients, servers, summary = await mcp_runtime.reload_mcp_servers(
            new_servers=[s_a, s_b],
            current_clients=[existing],
            current_servers_resolved=[s_a],
        )
    create.assert_awaited_once()
    assert clients == [existing, new_client]
    assert {s.name for s in servers} == {'a', 'b'}
    assert summary['added'] == ['b']
    assert summary['removed'] == []


@pytest.mark.asyncio
async def test_reload_reconnects_changed_server() -> None:
    existing = _make_client('github', type_='stdio')
    s_old = _server('github', type_='stdio', args=['--old'])
    s_new = _server('github', type_='stdio', args=['--new'])
    new_client = _make_client('github', type_='stdio')
    with patch.object(
        mcp_utils_mod,
        'create_mcps',
        AsyncMock(return_value=[new_client]),
    ) as create:
        clients, servers, summary = await mcp_runtime.reload_mcp_servers(
            new_servers=[s_new],
            current_clients=[existing],
            current_servers_resolved=[s_old],
        )
    existing.disconnect.assert_awaited_once()
    create.assert_awaited_once()
    assert clients == [new_client]
    assert servers == [s_new]
    assert summary['reconnected'] == ['github']


@pytest.mark.asyncio
async def test_reload_reports_failed_connection() -> None:
    s = _server('broken')
    with patch.object(
        mcp_utils_mod,
        'create_mcps',
        AsyncMock(return_value=[]),
    ):
        clients, servers, summary = await mcp_runtime.reload_mcp_servers(
            new_servers=[s],
            current_clients=None,
            current_servers_resolved=None,
        )
    assert clients == []
    assert summary['failed'] == ['broken']


@pytest.mark.asyncio
async def test_reload_tolerates_disconnect_failure() -> None:
    existing = _make_client('old', disconnect_fail=True)
    new = _server('new')
    with patch.object(
        mcp_utils_mod,
        'create_mcps',
        AsyncMock(return_value=[]),
    ):
        clients, _servers, summary = await mcp_runtime.reload_mcp_servers(
            new_servers=[new],
            current_clients=[existing],
            current_servers_resolved=[_server('old')],
        )
    existing.disconnect.assert_awaited_once()
    assert summary['removed'] == ['old']


@pytest.mark.asyncio
async def test_reload_empty_inputs_is_noop() -> None:
    clients, servers, summary = await mcp_runtime.reload_mcp_servers(
        new_servers=[],
        current_clients=None,
        current_servers_resolved=None,
    )
    assert clients == []
    assert servers == []
    assert summary == {
        'added': [],
        'removed': [],
        'reconnected': [],
        'unchanged': [],
        'failed': [],
    }


@pytest.mark.asyncio
async def test_reload_drop_stale_client_when_identity_added() -> None:
    """A client whose server identity is *not* in the new pool must be
    dropped, even if no key overlaps. Guards against operator errors
    where the executor accumulates stale clients across reloads.
    """
    stale = _make_client('stale', type_='sse')
    s = _server('fresh', type_='stdio')
    new_client = _make_client('fresh', type_='stdio')
    with patch.object(
        mcp_utils_mod,
        'create_mcps',
        AsyncMock(return_value=[new_client]),
    ):
        clients, _, summary = await mcp_runtime.reload_mcp_servers(
            new_servers=[s],
            current_clients=[stale],
            current_servers_resolved=[_server('stale', type_='sse')],
        )
    stale.disconnect.assert_awaited_once()
    assert clients == [new_client]
    assert summary['added'] == ['fresh']
    assert summary['removed'] == ['stale']
