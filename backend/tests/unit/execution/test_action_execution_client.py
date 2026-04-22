"""Tests for ActionExecutionClient HTTP helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.execution.drivers.action_execution.action_execution_client import (
    ActionExecutionClient,
)
from backend.utils.http_session import HttpSession


def test_send_action_server_request_uses_http_session() -> None:
    client = ActionExecutionClient.__new__(ActionExecutionClient)
    client._action_server_session = HttpSession()
    client.action_execution_server_url = 'http://127.0.0.1:9'

    with patch(
        'backend.execution.drivers.action_execution.action_execution_client.send_request'
    ) as send_request:
        mock_resp = MagicMock()
        send_request.return_value = mock_resp
        result = ActionExecutionClient._send_action_server_request(
            client, 'GET', '/ping'
        )
        assert result is mock_resp
        send_request.assert_called_once()
        session_arg, method, url = send_request.call_args[0]
        assert isinstance(session_arg, HttpSession)
        assert session_arg is client._action_server_session
        assert method == 'GET'
        assert url == 'http://127.0.0.1:9/ping'
