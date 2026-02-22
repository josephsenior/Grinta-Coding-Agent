import importlib
import os
from contextlib import contextmanager
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


@contextmanager
def build_client(env: dict, tracer_store: list[_TestSpan] | None = None):
    # Apply environment overrides for this test scope.
    # Disable session API key enforcement for this in-process TestClient.
    # Auth is normally enabled by default (auto-generated key), but these
    # OTEL sampling tests only care about span creation, not auth.
    env = {"SESSION_API_KEY": "", **env}

    # OTEL config prefers TRACING_ENABLED over OTEL_ENABLED.
    # Mirror the setting so test behavior is stable regardless of outer env.
    if "OTEL_ENABLED" in env and "TRACING_ENABLED" not in env:
        env["TRACING_ENABLED"] = env["OTEL_ENABLED"]

    original_env = {k: os.environ.get(k) for k in env.keys()}
    for k, v in env.items():
        os.environ[k] = v

    # Ensure our fake tracer is used during app import
    import opentelemetry.trace as ot_trace

    original_get_tracer = getattr(ot_trace, "get_tracer", None)
    if tracer_store is not None:
        fake = _TestTracer(tracer_store)

        def _get_tracer(*_args, **_kwargs):
            return fake

        setattr(ot_trace, "get_tracer", _get_tracer)

    # Reload modules in-place so OTEL config reflects env set above,
    # without swapping module identities (which breaks later patching).
    import backend.api.otel_config as otel_config  # type: ignore
    import backend.api.route_registry as route_registry  # type: ignore
    import backend.api.app as app_module  # type: ignore

    importlib.reload(otel_config)
    importlib.reload(route_registry)
    importlib.reload(app_module)

    app = app_module.app
    client = TestClient(app)
    try:
        yield client
    finally:
        try:
            client.close()
        except Exception:
            pass

        if tracer_store is not None and original_get_tracer is not None:
            setattr(ot_trace, "get_tracer", original_get_tracer)

        for k, old_value in original_env.items():
            if old_value is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old_value


def test_span_created_for_high_sample_rate():
    # Enable OTEL and high sampling for a specific route
    env = {
        "OTEL_ENABLED": "true",
        "OTEL_SAMPLE_HTTP": "0.0",  # base 0 so only overrides matter
        "OTEL_SAMPLE_ROUTES": "/api/v1/test-exact:1.0",
    }
    spans: list[_TestSpan] = []

    with build_client(env, tracer_store=spans) as client:
        # Route not covered: expect NO span (base 0.0)
        r1 = client.get("/api/v1/other")
        assert r1.status_code in (200, 404, 422)

        # Covered route: expect span created
        r2 = client.get("/api/v1/test-exact")
        assert r2.status_code in (200, 404, 422)

    names = [s.name for s in spans]
    assert any("/api/v1/test-exact" in n for n in names), f"Spans: {names}"
    assert not any("/api/v1/other" in n for n in names), f"Unexpected spans: {names}"


def test_span_skipped_for_low_sample_rate():
    env = {
        "OTEL_ENABLED": "true",
        "OTEL_SAMPLE_HTTP": "1.0",  # base high
        "OTEL_SAMPLE_ROUTES": "/api/v1/skip-me:0.0",
    }
    spans: list[_TestSpan] = []

    with build_client(env, tracer_store=spans) as client:
        # Route with explicit 0 sample: expect no span
        r = client.get("/api/v1/skip-me")
        assert r.status_code in (200, 404, 422)
    names = [s.name for s in spans]
    assert not any("/api/v1/skip-me" in n for n in names), f"Spans: {names}"


def test_debug_endpoint_reports_effective():
    env = {
        "OTEL_ENABLED": "true",
        "OTEL_SAMPLE_HTTP": "0.25",
        "OTEL_SAMPLE_ROUTES": "/api/v1/prefix/*:0.75;/api/v1/exact:1.0",
        "OTEL_SAMPLE_ROUTES_REGEX": "^/api/v1/regex[0-9]+:0.9",
        "OTEL_DEBUG_SAMPLING": "true",
    }
    with build_client(env) as client:
        resp = client.get(
            "/api/v1/monitoring/sampling_debug", params={"path": "/api/v1/regex123"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["base_http_sample"] == 0.25
        assert data["effective_for"]["path"] == "/api/v1/regex123"
        assert data["effective_for"]["effective_rate"] == 0.9  # regex precedence

        resp2 = client.get(
            "/api/v1/monitoring/sampling_debug",
            params={"path": "/api/v1/prefix/abc"},
        )
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["effective_for"]["effective_rate"] == 0.75

        resp3 = client.get(
            "/api/v1/monitoring/sampling_debug", params={"path": "/api/v1/exact"}
        )
        data3 = resp3.json()
        assert data3["effective_for"]["effective_rate"] == 1.0

        resp4 = client.get(
            "/api/v1/monitoring/sampling_debug", params={"path": "/api/v1/unknown"}
        )
        data4 = resp4.json()
        assert data4["effective_for"]["effective_rate"] == 0.25
