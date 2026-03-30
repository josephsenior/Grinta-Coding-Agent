"""Tests for canonical local server startup planning."""

from __future__ import annotations

import io
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.gateway.cli.server_startup import (
    ServerStartupPlan,
    add_project_root_to_path,
    build_server_startup_plan,
    ensure_utf8_stdout,
    load_dotenv_local,
    print_server_startup_preflight,
    record_startup_snapshot,
    validate_storage_contract,
)


def test_build_server_startup_plan_uses_local_defaults(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("APP_HOST", raising=False)
    monkeypatch.delenv("HOST", raising=False)
    monkeypatch.delenv("APP_PORT", raising=False)
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.delenv("APP_RUNTIME", raising=False)
    monkeypatch.setenv("APP_ROOT", str(tmp_path / "app-root"))

    plan = build_server_startup_plan(tmp_path)

    assert plan.host == "127.0.0.1"
    assert plan.requested_port == 3000
    assert plan.runtime == "local"
    assert plan.settings_path.endswith("settings.json")
    assert plan.health_url.endswith("/api/health/ready")


def test_build_server_startup_plan_prefers_app_port(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("APP_PORT", "3131")
    monkeypatch.setenv("PORT", "3000")
    monkeypatch.setenv("APP_ROOT", str(tmp_path / "app-root"))

    plan = build_server_startup_plan(tmp_path)

    assert plan.requested_port == 3131
    assert plan.resolved_port == 3131


def test_build_server_startup_plan_detects_agent_yaml(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("APP_ROOT", str(tmp_path / "app-root"))
    (tmp_path / "agent.yaml").write_text("name: demo\n", encoding="utf-8")

    plan = build_server_startup_plan(tmp_path)

    assert plan.agent_config_present is True


def test_server_startup_plan_snapshot_round_trip() -> None:
    plan = ServerStartupPlan(
        host="127.0.0.1",
        requested_port=3000,
        resolved_port=3001,
        port_auto_switched=True,
        reload_enabled=False,
        runtime="local",
        project_root="/p",
        cwd="/c",
        app_root="/a",
        settings_path="/a/settings.json",
        dotenv_local_loaded=False,
        agent_config_present=False,
        ui_url="http://127.0.0.1:3001",
        api_url="http://127.0.0.1:3001/api",
        docs_url="http://127.0.0.1:3001/docs",
        health_url="http://127.0.0.1:3001/api/health/ready",
    )
    snap = plan.snapshot()
    assert snap["resolved_port"] == 3001
    assert snap["port_auto_switched"] is True
    assert snap["health_url"].endswith("/ready")


def test_load_dotenv_local_fills_only_blank_keys(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env.local"
    dotenv.write_text(
        'EXISTING=from_file\n# comment\nNEW_KEY="quoted"\nBLANK_WILL_SET=  x  \n',
        encoding="utf-8",
    )
    env: dict[str, str] = {"EXISTING": "  keep  ", "BLANK_WILL_SET": ""}
    assert load_dotenv_local(tmp_path, env) is True
    assert env["EXISTING"] == "  keep  "
    assert env["NEW_KEY"] == "quoted"
    assert env["BLANK_WILL_SET"] == "x"


def test_load_dotenv_local_missing_returns_false(tmp_path: Path) -> None:
    env: dict[str, str] = {}
    assert load_dotenv_local(tmp_path, env) is False


def test_validate_storage_contract_noop_for_file_mode() -> None:
    env = {"APP_KB_STORAGE_TYPE": "file", "DATABASE_URL": ""}
    validate_storage_contract(env)


def test_validate_storage_contract_exits_when_db_without_url() -> None:
    env = {"APP_KB_STORAGE_TYPE": "database", "DATABASE_URL": "  "}
    with pytest.raises(SystemExit) as exc:
        validate_storage_contract(env)
    assert exc.value.code == 2


def test_add_project_root_to_path_idempotent(tmp_path: Path) -> None:
    root = str(tmp_path.resolve())
    before = list(sys.path)
    try:
        add_project_root_to_path(tmp_path)
        add_project_root_to_path(tmp_path)
        assert sys.path[0] == root
        assert sys.path.count(root) == 1
    finally:
        sys.path[:] = before


def test_ensure_utf8_stdout_reconfigure_utf8(monkeypatch) -> None:
    mock_stdout = MagicMock()
    mock_stdout.encoding = "cp1252"
    mock_stdout.reconfigure = MagicMock()
    monkeypatch.setattr(sys, "stdout", mock_stdout)
    ensure_utf8_stdout()
    mock_stdout.reconfigure.assert_called_once_with(encoding="utf-8", errors="replace")


def test_ensure_utf8_stdout_skips_when_already_utf8(monkeypatch) -> None:
    mock_stdout = MagicMock()
    mock_stdout.encoding = "utf-8"
    monkeypatch.setattr(sys, "stdout", mock_stdout)
    ensure_utf8_stdout()
    mock_stdout.reconfigure.assert_not_called()


def test_print_server_startup_preflight_emits_urls() -> None:
    buf = io.StringIO()
    plan = ServerStartupPlan(
        host="0.0.0.0",
        requested_port=3000,
        resolved_port=3000,
        port_auto_switched=False,
        reload_enabled=False,
        runtime="local",
        project_root="/p",
        cwd="/c",
        app_root="/a",
        settings_path="/a/settings.json",
        dotenv_local_loaded=True,
        agent_config_present=True,
        ui_url="http://127.0.0.1:3000",
        api_url="http://127.0.0.1:3000/api",
        docs_url="http://127.0.0.1:3000/docs",
        health_url="http://127.0.0.1:3000/api/health/ready",
    )
    def emit(line: str) -> None:
        buf.write(f"{line}\n")

    print_server_startup_preflight(plan, emit=emit)
    out = buf.getvalue()
    assert "Local server preflight" in out
    assert "127.0.0.1:3000" in out or "health" in out


def test_print_server_startup_preflight_port_switch_line() -> None:
    buf = io.StringIO()
    plan = ServerStartupPlan(
        host="127.0.0.1",
        requested_port=3000,
        resolved_port=3005,
        port_auto_switched=True,
        reload_enabled=False,
        runtime="local",
        project_root="/p",
        cwd="/c",
        app_root="/a",
        settings_path="/a/settings.json",
        dotenv_local_loaded=False,
        agent_config_present=False,
        ui_url="http://127.0.0.1:3005",
        api_url="http://127.0.0.1:3005/api",
        docs_url="http://127.0.0.1:3005/docs",
        health_url="http://127.0.0.1:3005/api/health/ready",
    )
    def emit(line: str) -> None:
        buf.write(f"{line}\n")

    print_server_startup_preflight(plan, emit=emit)
    assert "3000 requested" in buf.getvalue()
    assert "3005 selected" in buf.getvalue()


@patch("backend.gateway.cli.server_startup.socket.socket")
def test_build_server_startup_plan_finds_next_port_when_busy(
    mock_socket_class, monkeypatch, tmp_path: Path
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("APP_ROOT", str(tmp_path / "app-root"))
    monkeypatch.setenv("APP_PORT", "9999")

    def bind_side_effect(addr):
        _host, port = addr
        if port == 9999:
            raise OSError("Address already in use")

    mock_sock = MagicMock()
    mock_sock.__enter__ = MagicMock(return_value=mock_sock)
    mock_sock.__exit__ = MagicMock(return_value=False)
    mock_sock.bind = MagicMock(side_effect=bind_side_effect)
    mock_socket_class.return_value = mock_sock

    plan = build_server_startup_plan(tmp_path)

    assert plan.requested_port == 9999
    assert plan.resolved_port == 10000
    assert plan.port_auto_switched is True


def test_record_startup_snapshot_delegates_to_app_state(monkeypatch) -> None:
    mock_state = MagicMock()
    monkeypatch.setattr(
        "backend.gateway.app_state.get_app_state",
        lambda: mock_state,
    )
    plan = ServerStartupPlan(
        host="127.0.0.1",
        requested_port=3000,
        resolved_port=3000,
        port_auto_switched=False,
        reload_enabled=False,
        runtime="local",
        project_root="/p",
        cwd="/c",
        app_root="/a",
        settings_path="/a/settings.json",
        dotenv_local_loaded=False,
        agent_config_present=False,
        ui_url="http://127.0.0.1:3000/",
        api_url="http://127.0.0.1:3000/api",
        docs_url="http://127.0.0.1:3000/docs",
        health_url="http://127.0.0.1:3000/api/health/ready",
    )
    record_startup_snapshot(plan)
    mock_state.record_startup_snapshot.assert_called_once_with(plan.snapshot())