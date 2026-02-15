import importlib
import os
from typing import TYPE_CHECKING

from fastapi.testclient import TestClient

if TYPE_CHECKING:
    pass


class _TestSpan:
    def __init__(self, name: str, store: "list[_TestSpan]"):
        self.name = name
        self._store = store
        self.attributes: dict[str, object] = {}

    def __enter__(self):
        # record when span starts
        self._store.append(self)
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def set_attribute(self, key, value):
        self.attributes[key] = value

    def record_exception(self, e):
        self.attributes["exception.type"] = type(e).__name__


class _TestTracer:
    def __init__(self, store: list[_TestSpan]):
        self._store = store

    def start_as_current_span(self, name: str, kind=None):
        return _TestSpan(name, self._store)


def build_client(env: dict, tracer_store: list[_TestSpan] | None = None):
    # Apply environment overrides for this test scope
    for k, v in env.items():
        os.environ[k] = v

    # Ensure our fake tracer is used during app import
    import opentelemetry.trace as ot_trace

    if tracer_store is not None:
        fake = _TestTracer(tracer_store)

        def _get_tracer(_name: str = "backend.server"):
            return fake

        setattr(ot_trace, "get_tracer", _get_tracer)

    # Force a fresh import of the app module
    import sys

    if "backend.server.app" in sys.modules:
        importlib.reload(importlib.import_module("backend.server.app"))
    from backend.server.app import app  # type: ignore

    return TestClient(app)


def test_span_created_for_high_sample_rate():
    # Enable OTEL and high sampling for a specific route
    env = {
        "OTEL_ENABLED": "true",
        "OTEL_SAMPLE_HTTP": "0.0",  # base 0 so only overrides matter
        "OTEL_SAMPLE_ROUTES": "/api/test-exact:1.0",
    }
    spans: list[_TestSpan] = []
    client = build_client(env, tracer_store=spans)

    # Route not covered: expect NO span (base 0.0)
    r1 = client.get("/api/other")
    assert r1.status_code in (200, 404, 422)

    # Covered route: expect span created
    r2 = client.get("/api/test-exact")
    assert r2.status_code in (200, 404, 422)

    names = [s.name for s in spans]
    assert any("/api/test-exact" in n for n in names), f"Spans: {names}"
    assert not any("/api/other" in n for n in names), f"Unexpected spans: {names}"


def test_span_skipped_for_low_sample_rate():
    env = {
        "OTEL_ENABLED": "true",
        "OTEL_SAMPLE_HTTP": "1.0",  # base high
        "OTEL_SAMPLE_ROUTES": "/api/skip-me:0.0",
    }
    spans: list[_TestSpan] = []
    client = build_client(env, tracer_store=spans)

    # Route with explicit 0 sample: expect no span
    r = client.get("/api/skip-me")
    assert r.status_code in (200, 404, 422)
    names = [s.name for s in spans]
    assert not any("/api/skip-me" in n for n in names), f"Spans: {names}"


def test_debug_endpoint_reports_effective():
    env = {
        "OTEL_ENABLED": "true",
        "OTEL_SAMPLE_HTTP": "0.25",
        "OTEL_SAMPLE_ROUTES": "/api/prefix/*:0.75;/api/exact:1.0",
        "OTEL_SAMPLE_ROUTES_REGEX": "^/api/regex[0-9]+:0.9",
        "OTEL_DEBUG_SAMPLING": "true",
    }
    client = build_client(env)

    resp = client.get(
        "/api/monitoring/sampling_debug", params={"path": "/api/regex123"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["base_http_sample"] == 0.25
    assert data["effective_for"]["path"] == "/api/regex123"
    assert data["effective_for"]["effective_rate"] == 0.9  # regex precedence

    resp2 = client.get(
        "/api/monitoring/sampling_debug", params={"path": "/api/prefix/abc"}
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["effective_for"]["effective_rate"] == 0.75

    resp3 = client.get("/api/monitoring/sampling_debug", params={"path": "/api/exact"})
    data3 = resp3.json()
    assert data3["effective_for"]["effective_rate"] == 1.0

    resp4 = client.get(
        "/api/monitoring/sampling_debug", params={"path": "/api/unknown"}
    )
    data4 = resp4.json()
    assert data4["effective_for"]["effective_rate"] == 0.25
