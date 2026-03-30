"""Tests for backend.gateway.routes.health."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.gateway.routes.health import (
    _check_config,
    _check_database,
    _check_recovery,
    _check_redis,
    _check_startup,
    _check_storage,
    _check_tmux,
    add_health_endpoints,
)


def _make_client() -> TestClient:
    app = FastAPI()
    add_health_endpoints(app)
    return TestClient(app)


def test_check_redis_not_configured(monkeypatch):
    monkeypatch.delenv("REDIS_HOST", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    result = _check_redis()
    assert result["status"] == "not_configured"


def test_check_database_not_configured_file_mode(monkeypatch):
    monkeypatch.setenv("APP_KB_STORAGE_TYPE", "file")
    result = _check_database()
    assert result["status"] == "not_configured"


def test_check_database_missing_url(monkeypatch):
    monkeypatch.setenv("APP_KB_STORAGE_TYPE", "database")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    result = _check_database()
    assert result["status"] == "error"
    assert "missing" in result["detail"].lower()


def test_check_tmux_degraded_when_missing():
    with patch("backend.gateway.routes.health.shutil.which", return_value=None):
        result = _check_tmux()
    assert result["status"] == "degraded"
    assert result["available"] is False


def test_health_ready_200_with_critical_checks_ok():
    client = _make_client()
    with (
        patch("backend.gateway.routes.health._check_config", return_value={"status": "ok"}),
        patch("backend.gateway.routes.health._check_storage", return_value={"status": "ok"}),
        patch("backend.gateway.routes.health._check_redis", return_value={"status": "degraded"}),
        patch("backend.gateway.routes.health._check_database", return_value={"status": "degraded"}),
        patch("backend.gateway.routes.health._check_tmux", return_value={"status": "degraded"}),
        patch("backend.gateway.routes.health._check_recovery", return_value={"status": "ok"}),
        patch("backend.gateway.routes.health._check_startup", return_value={"status": "unknown"}),
    ):
        resp = client.get("/api/health/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert "redis" in body["checks"]
    assert "database" in body["checks"]
    assert "tmux" in body["checks"]


def test_health_ready_503_when_critical_check_fails():
    client = _make_client()
    with (
        patch("backend.gateway.routes.health._check_config", return_value={"status": "error"}),
        patch("backend.gateway.routes.health._check_storage", return_value={"status": "ok"}),
        patch("backend.gateway.routes.health._check_redis", return_value={"status": "ok"}),
        patch("backend.gateway.routes.health._check_database", return_value={"status": "ok"}),
        patch("backend.gateway.routes.health._check_tmux", return_value={"status": "ok"}),
        patch("backend.gateway.routes.health._check_recovery", return_value={"status": "ok"}),
        patch("backend.gateway.routes.health._check_startup", return_value={"status": "unknown"}),
    ):
        resp = client.get("/api/health/ready")
    assert resp.status_code == 503
    assert resp.json()["status"] == "not_ready"


def test_check_recovery_reports_state_restore_snapshot():
    fake_app_state = MagicMock()
    fake_app_state.get_state_restore_snapshot.return_value = {
        "count": 1,
        "recent": [{"sid": "abc", "source": "checkpoint", "path": "state.json"}],
    }
    with (
        patch("backend.gateway.app_state.get_app_state", return_value=fake_app_state),
        patch(
            "backend.ledger.stream_stats.get_aggregated_event_stream_stats",
            return_value={"streams": 0, "persist_failures": 0, "durable_writer_errors": 0},
        ),
    ):
        result = _check_recovery()

    assert result["status"] == "ok"
    assert result["state_restores"]["count"] == 1
    assert result["state_restores"]["recent"][0]["source"] == "checkpoint"


def test_check_startup_reports_latest_snapshot():
    fake_app_state = MagicMock()
    fake_app_state.get_startup_snapshot.return_value = {
        "host": "127.0.0.1",
        "resolved_port": 3000,
        "settings_path": "settings.json",
    }
    with patch("backend.gateway.app_state.get_app_state", return_value=fake_app_state):
        result = _check_startup()

    assert result["status"] == "ok"
    assert result["server"]["resolved_port"] == 3000


def test_health_ready_includes_startup_check():
    client = _make_client()
    with (
        patch("backend.gateway.routes.health._check_config", return_value={"status": "ok"}),
        patch("backend.gateway.routes.health._check_storage", return_value={"status": "ok"}),
        patch("backend.gateway.routes.health._check_redis", return_value={"status": "ok"}),
        patch("backend.gateway.routes.health._check_database", return_value={"status": "ok"}),
        patch("backend.gateway.routes.health._check_tmux", return_value={"status": "ok"}),
        patch("backend.gateway.routes.health._check_recovery", return_value={"status": "ok"}),
        patch("backend.gateway.routes.health._check_startup", return_value={"status": "ok", "server": {"resolved_port": 3000}}),
    ):
        resp = client.get("/api/health/ready")

    assert resp.status_code == 200
    assert resp.json()["checks"]["startup"]["server"]["resolved_port"] == 3000


def test_check_storage_ok(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()

    def fake_root():
        return str(root)

    monkeypatch.setattr(
        "backend.persistence.locations.get_local_data_root",
        fake_root,
    )
    result = _check_storage()
    assert result["status"] == "ok"
    assert result["path"] == str(root)


def test_check_storage_degraded_not_writable(tmp_path, monkeypatch):
    root = tmp_path / "ro"
    root.mkdir()

    monkeypatch.setattr(
        "backend.persistence.locations.get_local_data_root",
        lambda: str(root),
    )
    monkeypatch.setattr("os.access", lambda *_a, **_k: False)

    result = _check_storage()
    assert result["status"] == "degraded"
    assert result["path"] == str(root)


def test_check_storage_error(monkeypatch):
    def boom():
        raise RuntimeError("no store")

    monkeypatch.setattr("backend.persistence.locations.get_local_data_root", boom)
    result = _check_storage()
    assert result["status"] == "error"
    assert "no store" in result["detail"]


def test_check_config_ok(monkeypatch):
    cfg = MagicMock()
    cfg.project_root = "/proj"
    cfg.local_data_root = "/data"

    monkeypatch.setattr("backend.core.config.load_app_config", lambda: cfg)
    result = _check_config()
    assert result["status"] == "ok"
    assert result["project_root"] == "/proj"
    assert result["local_data_root"] == "/data"


def test_check_config_error(monkeypatch):
    monkeypatch.setattr(
        "backend.core.config.load_app_config",
        MagicMock(side_effect=OSError("broken")),
    )
    result = _check_config()
    assert result["status"] == "error"
    assert "broken" in result["detail"]


def test_check_redis_host_reachable(monkeypatch):
    monkeypatch.setenv("REDIS_HOST", "127.0.0.1")
    monkeypatch.setenv("REDIS_PORT", "6379")
    monkeypatch.delenv("REDIS_URL", raising=False)

    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = None
    mock_cm.__exit__.return_value = None
    with patch("backend.gateway.routes.health.socket.create_connection", return_value=mock_cm):
        result = _check_redis()

    assert result["status"] == "ok"
    assert result["reachable"] is True
    assert result["port"] == 6379


def test_check_redis_host_not_reachable(monkeypatch):
    monkeypatch.setenv("REDIS_HOST", "10.0.0.1")
    monkeypatch.delenv("REDIS_URL", raising=False)

    with patch(
        "backend.gateway.routes.health.socket.create_connection",
        side_effect=OSError("refused"),
    ):
        result = _check_redis()

    assert result["status"] == "degraded"
    assert result["reachable"] is False


def test_check_redis_url_without_host(monkeypatch):
    monkeypatch.delenv("REDIS_HOST", raising=False)
    monkeypatch.setenv("REDIS_URL", "redis://cache:6379/0")

    result = _check_redis()
    assert result["status"] == "configured"
    assert result["reachable"] == "unknown"


def test_check_redis_invalid_port_defaults(monkeypatch):
    monkeypatch.setenv("REDIS_HOST", "127.0.0.1")
    monkeypatch.setenv("REDIS_PORT", "not-int")
    monkeypatch.delenv("REDIS_URL", raising=False)

    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = None
    mock_cm.__exit__.return_value = None
    with patch("backend.gateway.routes.health.socket.create_connection", return_value=mock_cm):
        result = _check_redis()

    assert result["port"] == 6379


def test_check_database_db_alias_and_reachable(monkeypatch):
    monkeypatch.setenv("APP_KB_STORAGE_TYPE", "db")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setenv("POSTGRES_HOST", "127.0.0.1")
    monkeypatch.setenv("POSTGRES_PORT", "5432")

    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = None
    mock_cm.__exit__.return_value = None
    with patch("backend.gateway.routes.health.socket.create_connection", return_value=mock_cm):
        result = _check_database()

    assert result["status"] == "ok"
    assert result["reachable"] is True


def test_check_database_invalid_postgres_port(monkeypatch):
    monkeypatch.setenv("APP_KB_STORAGE_TYPE", "database")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setenv("POSTGRES_PORT", "oops")

    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = None
    mock_cm.__exit__.return_value = None
    with patch("backend.gateway.routes.health.socket.create_connection", return_value=mock_cm):
        result = _check_database()

    assert result["port"] == 5432


def test_check_tmux_ok():
    with patch("backend.gateway.routes.health.shutil.which", return_value="/usr/bin/tmux"):
        result = _check_tmux()

    assert result["status"] == "ok"
    assert result["available"] is True
    assert result["path"] == "/usr/bin/tmux"


def test_check_recovery_degraded_on_stream_errors():
    fake_app_state = MagicMock()
    fake_app_state.get_state_restore_snapshot.return_value = {"count": 0, "recent": []}
    with (
        patch("backend.gateway.app_state.get_app_state", return_value=fake_app_state),
        patch(
            "backend.ledger.stream_stats.get_aggregated_event_stream_stats",
            return_value={"persist_failures": 1, "durable_writer_errors": 0},
        ),
    ):
        result = _check_recovery()

    assert result["status"] == "degraded"


def test_check_recovery_on_inner_exception():
    with patch(
        "backend.gateway.app_state.get_app_state",
        side_effect=RuntimeError("state boom"),
    ):
        result = _check_recovery()

    assert result["status"] == "error"
    assert "state boom" in result["detail"]


def test_check_startup_unknown_when_empty():
    fake_app_state = MagicMock()
    fake_app_state.get_startup_snapshot.return_value = {}

    with patch("backend.gateway.app_state.get_app_state", return_value=fake_app_state):
        result = _check_startup()

    assert result["status"] == "unknown"


def test_check_startup_error():
    with patch(
        "backend.gateway.app_state.get_app_state",
        side_effect=ValueError("nope"),
    ):
        result = _check_startup()

    assert result["status"] == "error"
    assert "nope" in result["detail"]


def test_alive_endpoint():
    client = _make_client()
    r = client.get("/alive")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_health_live_includes_uptime():
    client = _make_client()
    r = client.get("/api/health/live")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "uptime_seconds" in body
    assert isinstance(body["uptime_seconds"], (int, float))


def test_server_info_delegates_to_get_system_info():
    payload = {"uptime": 1.0, "idle_time": 0.5, "resources": {}}
    client = _make_client()
    with patch.object(
        __import__("backend.gateway.routes.health", fromlist=["x"]),
        "get_system_info",
        return_value=payload,
    ):
        r = client.get("/server_info")

    assert r.status_code == 200
    assert r.json() == payload


def test_health_ready_503_when_storage_degraded():
    client = _make_client()
    with (
        patch("backend.gateway.routes.health._check_config", return_value={"status": "ok"}),
        patch(
            "backend.gateway.routes.health._check_storage",
            return_value={"status": "degraded", "path": "/x"},
        ),
        patch("backend.gateway.routes.health._check_redis", return_value={"status": "ok"}),
        patch("backend.gateway.routes.health._check_database", return_value={"status": "ok"}),
        patch("backend.gateway.routes.health._check_tmux", return_value={"status": "ok"}),
        patch("backend.gateway.routes.health._check_recovery", return_value={"status": "ok"}),
        patch("backend.gateway.routes.health._check_startup", return_value={"status": "unknown"}),
    ):
        resp = client.get("/api/health/ready")

    assert resp.status_code == 503
    assert resp.json()["status"] == "not_ready"
