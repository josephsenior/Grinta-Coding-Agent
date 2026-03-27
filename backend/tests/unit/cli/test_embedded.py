"""Tests for embedded mode startup planning delegation."""

from __future__ import annotations

import sys
from unittest.mock import Mock, patch

import pytest

from backend.embedded import _browser_url, _parse_args, _wait_for_server, run_embedded


@patch("backend.embedded.time.sleep", side_effect=[KeyboardInterrupt(), None])
@patch("backend.embedded.webbrowser.open")
@patch("backend.embedded._wait_for_server", return_value=True)
@patch("backend.embedded.threading.Thread")
@patch("backend.embedded.print_server_startup_preflight")
@patch("backend.embedded.record_startup_snapshot")
@patch("backend.embedded.validate_storage_contract")
@patch("backend.embedded.build_server_startup_plan")
def test_run_embedded_uses_canonical_startup_plan(
    mock_build_plan: Mock,
    mock_validate_contract: Mock,
    mock_record_snapshot: Mock,
    mock_print_preflight: Mock,
    mock_thread: Mock,
    mock_wait: Mock,
    mock_webbrowser_open: Mock,
    mock_sleep: Mock,
) -> None:
    plan = Mock()
    plan.host = "127.0.0.1"
    plan.resolved_port = 3000
    plan.ui_url = "http://127.0.0.1:3000"
    mock_build_plan.return_value = plan

    run_embedded(host="127.0.0.1", port=3000)

    mock_build_plan.assert_called_once()
    build_env = mock_build_plan.call_args[0][1]
    assert build_env["FORGE_HOST"] == "127.0.0.1"
    assert build_env["FORGE_PORT"] == "3000"
    assert build_env["FORGE_WATCH"] == "0"
    mock_validate_contract.assert_called_once_with(build_env)
    mock_record_snapshot.assert_called_once_with(plan)
    mock_print_preflight.assert_called_once_with(plan)
    mock_thread.assert_called_once()
    mock_wait.assert_called_once_with(plan.host, plan.resolved_port)
    mock_webbrowser_open.assert_called_once_with(plan.ui_url)


@pytest.mark.parametrize(
    ("host", "expected_host"),
    [
        ("0.0.0.0", "127.0.0.1"),
        ("::", "127.0.0.1"),
        ("::0", "127.0.0.1"),
        ("192.168.1.1", "192.168.1.1"),
    ],
)
def test_browser_url_maps_wildcard_listeners(host: str, expected_host: str) -> None:
    assert _browser_url(host, 8080) == f"http://{expected_host}:8080/"


@patch("backend.embedded.time.monotonic")
@patch("backend.embedded.time.sleep")
@patch("httpx.get")
def test_wait_for_server_success_on_first_ok_response(
    mock_get: Mock, mock_sleep: Mock, mock_mono: Mock
) -> None:
    # deadline = 0 + 5; first while-check 0 < 5 → one probe, then return.
    mock_mono.side_effect = [0.0, 0.0]
    mock_resp = Mock()
    mock_resp.is_success = True
    mock_get.return_value = mock_resp

    assert _wait_for_server("127.0.0.1", 3000, timeout=5.0) is True
    mock_get.assert_called_once()
    mock_sleep.assert_not_called()


@patch("backend.embedded.time.monotonic")
@patch("backend.embedded.time.sleep")
@patch("httpx.get")
def test_wait_for_server_false_after_timeout(
    mock_get: Mock, mock_sleep: Mock, mock_mono: Mock
) -> None:
    mock_mono.side_effect = [0.0, 0.0, 0.02, 0.04, 0.05]
    mock_get.side_effect = OSError("connection refused")

    assert _wait_for_server("127.0.0.1", 9, timeout=0.05) is False
    assert mock_get.call_count >= 1


@patch("backend.embedded.print")
@patch("backend.embedded.time.sleep", side_effect=[KeyboardInterrupt(), None])
@patch("backend.embedded.webbrowser.open")
@patch("backend.embedded._wait_for_server", return_value=False)
@patch("backend.embedded.threading.Thread")
@patch("backend.embedded.print_server_startup_preflight")
@patch("backend.embedded.record_startup_snapshot")
@patch("backend.embedded.validate_storage_contract")
@patch("backend.embedded.build_server_startup_plan")
def test_run_embedded_exits_when_server_not_ready(
    mock_build_plan: Mock,
    mock_validate_contract: Mock,
    mock_record_snapshot: Mock,
    mock_print_preflight: Mock,
    mock_thread: Mock,
    mock_wait: Mock,
    mock_webbrowser_open: Mock,
    mock_sleep: Mock,
    mock_print: Mock,
) -> None:
    plan = Mock()
    plan.host = "127.0.0.1"
    plan.resolved_port = 3000
    plan.ui_url = "http://127.0.0.1:3000"
    mock_build_plan.return_value = plan

    with pytest.raises(SystemExit) as exc:
        run_embedded(host="127.0.0.1", port=3000)

    assert exc.value.code == 1
    mock_webbrowser_open.assert_not_called()


def test_parse_args_explicit_flags(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["backend.embedded", "--host", "10.0.0.2", "--port", "4444", "-v"],
    )
    args = _parse_args()
    assert args.host == "10.0.0.2"
    assert args.port == 4444
    assert args.verbose is True
