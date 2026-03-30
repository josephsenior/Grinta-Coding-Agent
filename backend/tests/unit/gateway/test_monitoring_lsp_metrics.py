from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.gateway.routes.monitoring import router as monitoring_router
from backend.gateway.routes.monitoring import monitoring_helpers
from backend.gateway.routes.monitoring.metrics import _get_lsp_metrics_event_limit
from backend.ledger.observation.error import ErrorObservation


class _FakeEventStream:
    def __init__(self, events):
        self._events = events

    def search_events(self, reverse: bool = False, limit: int | None = None):
        events = list(reversed(self._events)) if reverse else list(self._events)
        if limit is not None:
            events = events[:limit]
        return events


class _FakeController:
    def __init__(self, events):
        self.event_stream = _FakeEventStream(events)


class _FakeSession:
    def __init__(self, events):
        self.controller = _FakeController(events)


class _FakeManager:
    def __init__(self, sessions):
        self._active_conversations = sessions


def _make_client() -> TestClient:
    app = FastAPI()
    app.include_router(monitoring_router)
    return TestClient(app)


def _lsp_event(latency_ms: int, has_error: bool):
    obs = ErrorObservation(content="sample")
    obs.tool_result = {
        "tool": "lsp_query",
        "command": "find_definition",
        "file": "/tmp/a.py",
        "latency_ms": latency_ms,
        "available": not has_error,
        "has_error": has_error,
    }
    return obs


def test_lsp_metrics_empty_when_no_manager(monkeypatch):
    monkeypatch.setattr(monitoring_helpers, "conversation_manager", None)
    client = _make_client()

    response = client.get("/api/v1/monitoring/lsp-metrics")
    assert response.status_code == 200
    body = response.json()
    assert body["sessions_scanned"] == 0
    assert body["samples"] == 0
    assert body["failures"] == 0
    assert body["failure_rate"] == 0.0
    assert body["latency_ms"] == {}


def test_lsp_metrics_aggregates_latency_and_failures(monkeypatch):
    session_a_events = [
        _lsp_event(10, False),
        _lsp_event(20, False),
        _lsp_event(30, True),
    ]
    session_b_events = [
        _lsp_event(40, False),
        _lsp_event(200, True),
    ]
    manager = _FakeManager(
        {
            "a": _FakeSession(session_a_events),
            "b": _FakeSession(session_b_events),
        }
    )
    monkeypatch.setattr(monitoring_helpers, "conversation_manager", manager)
    client = _make_client()

    response = client.get("/api/v1/monitoring/lsp-metrics")
    assert response.status_code == 200

    body = response.json()
    assert body["sessions_scanned"] == 2
    assert body["samples"] == 5
    assert body["failures"] == 2
    assert body["failure_rate"] == 0.4

    lat = body["latency_ms"]
    assert lat["min"] == 10.0
    assert lat["avg"] == 60.0
    assert lat["p50"] == 30.0
    assert lat["p95"] == 200.0
    assert lat["max"] == 200.0


def test_main_metrics_includes_nested_lsp_metrics(monkeypatch):
    manager = _FakeManager(
        {
            "a": _FakeSession([_lsp_event(15, False), _lsp_event(45, True)]),
        }
    )
    monkeypatch.setattr(monitoring_helpers, "conversation_manager", manager)
    client = _make_client()

    response = client.get("/api/v1/monitoring/metrics")
    assert response.status_code == 200

    body = response.json()
    lsp = body["system"]["lsp"]
    assert lsp["sessions_scanned"] == 1
    assert lsp["samples"] == 2
    assert lsp["failures"] == 1
    assert lsp["failure_rate"] == 0.5
    assert lsp["latency_ms"]["min"] == 15.0
    assert lsp["latency_ms"]["max"] == 45.0


def test_get_lsp_metrics_event_limit_reads_app_env(monkeypatch):
    monkeypatch.setenv("APP_LSP_METRICS_EVENT_LIMIT", "120")

    assert _get_lsp_metrics_event_limit() == 120


def test_get_lsp_metrics_event_limit_enforces_minimum(monkeypatch):
    monkeypatch.setenv("APP_LSP_METRICS_EVENT_LIMIT", "10")

    assert _get_lsp_metrics_event_limit() == 50
