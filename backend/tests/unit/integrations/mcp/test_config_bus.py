"""Unit tests for ``backend.integrations.mcp.config_bus``."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from backend.core.config.mcp_config import MCPConfig, MCPServerConfig
from backend.integrations.mcp.config_bus import (
    MCPConfigBus,
    diff_mcp_servers,
    get_mcp_config_bus,
    reset_mcp_config_bus,
)


@pytest.fixture(autouse=True)
def _reset_bus() -> Any:
    reset_mcp_config_bus()
    yield
    reset_mcp_config_bus()


def _server(
    name: str, *, type_: str = 'stdio', enabled: bool = True, **kwargs: Any
) -> MCPServerConfig:
    payload: dict[str, Any] = {'name': name, 'type': type_, 'enabled': enabled}
    if type_ == 'stdio':
        payload['command'] = kwargs.get('command', 'echo')
        payload['args'] = list(kwargs.get('args', []))
    else:
        payload['url'] = kwargs.get('url', 'http://localhost:8000')
    return MCPServerConfig(**payload)


# ── diff_mcp_servers ─────────────────────────────────────────────────


def test_diff_empty_inputs() -> None:
    diff = diff_mcp_servers(None, None)
    assert not diff.has_changes
    assert diff.added == []
    assert diff.removed == []
    assert diff.changed == {}


def test_diff_added_only() -> None:
    s = _server('github', type_='stdio')
    diff = diff_mcp_servers([], [s])
    assert diff.added == [s]
    assert diff.removed == []
    assert diff.changed == {}


def test_diff_removed_only() -> None:
    s = _server('github', type_='stdio')
    diff = diff_mcp_servers([s], [])
    assert diff.added == []
    assert diff.removed == [s]
    assert diff.changed == {}


def test_diff_unchanged() -> None:
    s = _server('github', type_='stdio')
    diff = diff_mcp_servers([s], [s])
    assert diff.added == []
    assert diff.removed == []
    assert diff.changed == {}
    assert diff.unchanged == [s]
    assert not diff.has_changes


def test_diff_changed_when_args_differ() -> None:
    old = _server('github', type_='stdio', args=['a'])
    new = _server('github', type_='stdio', args=['b'])
    diff = diff_mcp_servers([old], [new])
    assert diff.added == []
    assert diff.removed == []
    assert diff.changed[('github', 'stdio')] == (old, new)
    assert diff.has_changes


def test_diff_enabled_toggle_detected() -> None:
    old = _server('github', type_='stdio', enabled=True)
    new = _server('github', type_='stdio', enabled=False)
    diff = diff_mcp_servers([old], [new])
    assert diff.enabled_toggled == [new]
    assert diff.changed  # also marked as changed overall


def test_diff_type_change_treated_as_remove_plus_add() -> None:
    """Editing a server from stdio to sse keeps the name but is a fresh
    server identity; the old stdio client should be torn down and the
    new sse client brought up.
    """
    old = _server('github', type_='stdio')
    new = _server('github', type_='sse')
    diff = diff_mcp_servers([old], [new])
    assert diff.removed == [old]
    assert diff.added == [new]


# ── MCPConfigBus ─────────────────────────────────────────────────────


def test_bus_subscribe_unsubscribe() -> None:
    bus = MCPConfigBus()
    called: list[Any] = []

    def cb(change: Any) -> None:
        called.append(change)

    unsub = bus.subscribe(cb)
    bus.emit(MCPConfig(enabled=True, servers=[_server('a')]), source='mutation')
    assert len(called) == 1

    unsub()
    bus.emit(MCPConfig(enabled=True, servers=[_server('b')]), source='mutation')
    assert len(called) == 1


def test_bus_emits_diff_with_previous_snapshot() -> None:
    bus = MCPConfigBus()
    first = MCPConfig(enabled=True, servers=[_server('a')])
    bus.set_snapshot(first)
    captured: list[Any] = []
    bus.subscribe(lambda change: captured.append(change))
    bus.emit(
        MCPConfig(enabled=True, servers=[_server('a'), _server('b')]),
        source='mutation',
    )
    assert len(captured) == 1
    assert [s.name for s in captured[0].diff.added] == ['b']
    assert captured[0].source == 'mutation'


def test_bus_subscriber_exception_does_not_break_others() -> None:
    bus = MCPConfigBus()
    captured: list[Any] = []

    def bad(_: Any) -> None:
        raise RuntimeError('boom')

    def good(change: Any) -> None:
        captured.append(change)

    bus.subscribe(bad)
    bus.subscribe(good)
    bus.emit(MCPConfig(enabled=True, servers=[_server('a')]), source='mutation')
    assert len(captured) == 1


@pytest.mark.asyncio
async def test_bus_async_subscriber_awaited(monkeypatch: pytest.MonkeyPatch) -> None:
    bus = MCPConfigBus()
    captured: list[Any] = []

    async def cb(change: Any) -> None:
        await asyncio.sleep(0)
        captured.append(change)

    bus.subscribe(cb)
    bus.emit(MCPConfig(enabled=True, servers=[_server('a')]), source='mutation')
    # emit is fire-and-forget for async; wait briefly for the task.
    for _ in range(20):
        if captured:
            break
        await asyncio.sleep(0.01)
    assert len(captured) == 1


def test_bus_snapshot_and_source() -> None:
    bus = MCPConfigBus()
    assert bus.snapshot() is None
    assert bus.last_source() is None
    cfg = MCPConfig(enabled=True, servers=[_server('a')])
    bus.emit(cfg, source='file_watch')
    assert bus.snapshot() is cfg
    assert bus.last_source() == 'file_watch'


def test_get_mcp_config_bus_is_singleton() -> None:
    assert get_mcp_config_bus() is get_mcp_config_bus()
