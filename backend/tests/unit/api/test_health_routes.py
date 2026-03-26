"""Tests for backend.api.routes.health."""

from __future__ import annotations

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.health import (
    _check_database,
    _check_redis,
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
    monkeypatch.setenv("KB_STORAGE_TYPE", "file")
    result = _check_database()
    assert result["status"] == "not_configured"


def test_check_database_missing_url(monkeypatch):
    monkeypatch.setenv("KB_STORAGE_TYPE", "database")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    result = _check_database()
    assert result["status"] == "error"
    assert "missing" in result["detail"].lower()


def test_check_tmux_degraded_when_missing():
    with patch("backend.api.routes.health.shutil.which", return_value=None):
        result = _check_tmux()
    assert result["status"] == "degraded"
    assert result["available"] is False


def test_health_ready_200_with_critical_checks_ok():
    client = _make_client()
    with (
        patch("backend.api.routes.health._check_config", return_value={"status": "ok"}),
        patch("backend.api.routes.health._check_storage", return_value={"status": "ok"}),
        patch("backend.api.routes.health._check_redis", return_value={"status": "degraded"}),
        patch("backend.api.routes.health._check_database", return_value={"status": "degraded"}),
        patch("backend.api.routes.health._check_tmux", return_value={"status": "degraded"}),
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
        patch("backend.api.routes.health._check_config", return_value={"status": "error"}),
        patch("backend.api.routes.health._check_storage", return_value={"status": "ok"}),
        patch("backend.api.routes.health._check_redis", return_value={"status": "ok"}),
        patch("backend.api.routes.health._check_database", return_value={"status": "ok"}),
        patch("backend.api.routes.health._check_tmux", return_value={"status": "ok"}),
    ):
        resp = client.get("/api/health/ready")
    assert resp.status_code == 503
    assert resp.json()["status"] == "not_ready"
