from __future__ import annotations

from backend.integrations.mcp.mcp_bootstrap_status import (
    MCPBootstrapStatus,
    get_mcp_bootstrap_status,
    reset_mcp_bootstrap_status,
    set_mcp_bootstrap_status,
)


def test_mcp_bootstrap_status_defaults_and_reset() -> None:
    reset_mcp_bootstrap_status()
    status = get_mcp_bootstrap_status()
    assert status['state'] == 'unknown'
    assert status['mcp_enabled'] is False


def test_mcp_bootstrap_status_set_and_get() -> None:
    reset_mcp_bootstrap_status()
    s = MCPBootstrapStatus(
        state='healthy',
        mcp_enabled=True,
        configured_server_count=3,
        attempted_server_count=2,
        connected_client_count=2,
        remote_tool_param_count=7,
        conversion_errors=['x'],
        last_error=None,
    )
    set_mcp_bootstrap_status(s)
    out = get_mcp_bootstrap_status()
    assert out['state'] == 'healthy'
    assert out['connected_client_count'] == 2
    assert out['conversion_errors'] == ['x']
