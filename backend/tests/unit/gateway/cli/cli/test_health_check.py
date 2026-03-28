"""Unit tests for backend.gateway.cli.cli.health_check — ``forge health`` subcommand."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.gateway.cli.cli.health_check import run_health_check


@patch("backend.gateway.cli.cli.health_check.httpx.get")
def test_run_health_check_success(mock_get: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORGE_HOST", "127.0.0.1")
    monkeypatch.setenv("FORGE_PORT", "3001")
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"status": "ok"}
    mock_get.return_value = response

    run_health_check(None)

    mock_get.assert_called_once()
    assert mock_get.call_args[0][0] == "http://127.0.0.1:3001/alive"


@patch("backend.gateway.cli.cli.health_check.httpx.get")
def test_run_health_check_wildcard_host_maps_to_localhost(
    mock_get: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FORGE_HOST", "0.0.0.0")
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.delenv("FORGE_PORT", raising=False)
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"status": "ok"}
    mock_get.return_value = response

    run_health_check(None)

    assert mock_get.call_args[0][0] == "http://127.0.0.1:8080/alive"


@patch("backend.gateway.cli.cli.health_check.httpx.get", side_effect=OSError("refused"))
def test_run_health_check_connection_error(mock_get: MagicMock) -> None:
    with pytest.raises(SystemExit) as exc:
        run_health_check(None)
    assert exc.value.code == 1


@patch("backend.gateway.cli.cli.health_check.httpx.get")
def test_run_health_check_non_200(mock_get: MagicMock) -> None:
    response = MagicMock()
    response.status_code = 503
    mock_get.return_value = response

    with pytest.raises(SystemExit) as exc:
        run_health_check(None)
    assert exc.value.code == 1


@patch("backend.gateway.cli.cli.health_check.httpx.get")
def test_run_health_check_invalid_json(mock_get: MagicMock) -> None:
    response = MagicMock()
    response.status_code = 200
    response.json.side_effect = ValueError("not json")
    mock_get.return_value = response

    with pytest.raises(SystemExit) as exc:
        run_health_check(None)
    assert exc.value.code == 1


@patch("backend.gateway.cli.cli.health_check.httpx.get")
def test_run_health_check_unexpected_payload(mock_get: MagicMock) -> None:
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"status": "degraded"}
    mock_get.return_value = response

    with pytest.raises(SystemExit) as exc:
        run_health_check(None)
    assert exc.value.code == 1
