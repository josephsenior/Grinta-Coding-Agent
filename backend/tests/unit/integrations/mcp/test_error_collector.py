from __future__ import annotations

from backend.integrations.mcp.error_collector import MCPErrorCollector


def test_error_collector_add_get_count_clear() -> None:
    c = MCPErrorCollector()
    assert c.has_errors() is False
    assert c.get_error_count() == 0

    c.add_error('s1', 'stdio', 'boom', 'trace')
    assert c.has_errors() is True
    assert c.get_error_count() == 1
    errors = c.get_errors()
    assert len(errors) == 1
    assert errors[0].server_name == 's1'
    assert errors[0].exception_details == 'trace'

    c.clear_errors()
    assert c.get_error_count() == 0


def test_error_collector_disable_enable() -> None:
    c = MCPErrorCollector()
    c.disable_collection()
    c.add_error('s1', 'http', 'e1')
    assert c.get_error_count() == 0
    c.enable_collection()
    c.add_error('s2', 'http', 'e2')
    assert c.get_error_count() == 1

