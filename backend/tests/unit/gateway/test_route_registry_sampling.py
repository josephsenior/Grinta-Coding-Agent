"""Tests for OTEL sampling debug route registration in route_registry."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.gateway.route_registry import _register_sampling_debug


def test_sampling_debug_returns_config_and_effective_rate() -> None:
    app = FastAPI()
    _register_sampling_debug(app)
    client = TestClient(app)

    fake_regex = MagicMock()
    fake_regex.pattern = "^/api/.*"

    with (
        patch("backend.gateway.otel_config.OTEL_ENABLED", True),
        patch("backend.gateway.otel_config.SAMPLE_HTTP", 0.5),
        patch(
            "backend.gateway.otel_config.ROUTE_SAMPLE_PATTERNS",
            [("/api/settings", 0.2, True)],
        ),
        patch("backend.gateway.otel_config.ROUTE_SAMPLE_REGEX", [(fake_regex, 0.9)]),
        patch(
            "backend.gateway.otel_config.get_effective_http_sample", return_value=0.33
        ),
    ):
        r = client.get(
            "/api/v1/monitoring/sampling_debug", params={"path": "/api/foo"}
        )

    assert r.status_code == 200
    payload = r.json()
    assert payload["otel_enabled"] is True
    assert payload["base_http_sample"] == 0.5
    assert payload["effective_for"]["path"] == "/api/foo"
    assert payload["effective_for"]["effective_rate"] == 0.33
    assert len(payload["route_patterns"]) == 1
    assert payload["route_patterns"][0]["type"] == "prefix"
    assert len(payload["regex_patterns"]) == 1


def test_sampling_debug_error_when_effective_rate_fails() -> None:
    app = FastAPI()
    _register_sampling_debug(app)
    client = TestClient(app)

    with patch(
        "backend.gateway.otel_config.get_effective_http_sample",
        side_effect=RuntimeError("boom"),
    ):
        r = client.get(
            "/api/v1/monitoring/sampling_debug", params={"path": "/api/foo"}
        )

    assert r.status_code == 500
    assert "boom" in r.json()["error"]
