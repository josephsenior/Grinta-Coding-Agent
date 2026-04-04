"""Tests for backend.engine.tools.check_tool_status."""

from __future__ import annotations

import json

from backend.engine.tools.check_tool_status import (
    build_check_tool_status_action,
)


def _extract_status_payload(thought: str) -> dict:
    marker = '[TOOL_STATUS] '
    assert marker in thought
    payload_text = thought.split(marker, 1)[1]
    return json.loads(payload_text)


class TestBuildCheckToolStatusAction:
    """Test check_tool_status output contract."""

    def test_returns_structured_payload_for_all_tools(self):
        mcp_tools = {
            'read_component': {'function': {'name': 'read_component'}},
            'search_components': {'function': {'name': 'search_components'}},
        }

        action = build_check_tool_status_action({}, mcp_tools)
        payload = _extract_status_payload(action.thought)

        assert payload['scope'] == 'mcp_tools'
        assert payload['summary']['available_tool_count'] == 2
        assert payload['summary']['error_count'] == 0
        assert payload['degraded'] is False
        assert payload['tools'] == [
            {'name': 'read_component', 'status': 'ready', 'scope': 'mcp'},
            {'name': 'search_components', 'status': 'ready', 'scope': 'mcp'},
        ]

    def test_reports_specific_tool_not_found(self):
        mcp_tools = {'tool_a': {'function': {'name': 'tool_a'}}}

        action = build_check_tool_status_action({'tool_name': 'tool_b'}, mcp_tools)
        payload = _extract_status_payload(action.thought)

        assert payload['tools'] == [
            {'name': 'tool_b', 'status': 'not_found', 'scope': 'mcp'}
        ]

    def test_marks_degraded_when_connection_errors_present(self, monkeypatch):
        errors = [
            {
                'timestamp': 1700000000.0,
                'server': 'http://localhost:9000/mcp',
                'type': 'sse',
                'message': 'connection refused',
            }
        ]

        monkeypatch.setitem(
            build_check_tool_status_action.__globals__,
            '_collect_mcp_connection_errors',
            lambda: errors,
        )

        action = build_check_tool_status_action(
            {}, {'tool_a': {'function': {'name': 'tool_a'}}}
        )
        payload = _extract_status_payload(action.thought)

        assert payload['degraded'] is True
        assert payload['summary']['error_count'] == 1
        assert payload['recent_connection_errors'] == errors
        assert 'DEGRADED mode' in action.thought
