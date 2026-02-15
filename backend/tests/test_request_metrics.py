import re

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

from backend.server.middleware.request_metrics import RequestMetricsMiddleware
from backend.server.routes.monitoring import router as monitoring_router

# Access registry reset for deterministic tests
from typing import Callable

_reset_fn: Callable[[], None] | None = None
try:
    from backend.server.middleware.request_metrics import reset_request_metrics as _imported_reset
    _reset_fn = _imported_reset
except Exception:
    pass

reset_request_metrics: Callable[[], None] | None = _reset_fn


def _get_metric_value(body: str, metric: str):
    pattern = rf"^{re.escape(metric)}\s+(\d+(?:\.\d+)?)$"
    for line in body.strip().splitlines():
        m = re.match(pattern, line)
        if m:
            return float(m.group(1))
    return None


def _make_client() -> TestClient:
    test_app = FastAPI()
    test_app.include_router(monitoring_router)
    test_app.add_middleware(
        BaseHTTPMiddleware,
        dispatch=RequestMetricsMiddleware(enabled=True),
    )

    @test_app.get("/docs")
    async def docs():
        return {"title": "docs"}

    return TestClient(test_app)


def test_prometheus_metrics_expose_request_stats():
    client = _make_client()

    # Reset registry if available
    if reset_request_metrics is not None:
        reset_request_metrics()

    # Make a few requests to generate metrics
    r1 = client.get("/api/monitoring/health")
    assert r1.status_code == 200
    r2 = client.get("/docs")  # Swagger UI
    assert r2.status_code in (200, 404)  # swagger may be disabled in some configs

    # Fetch prom metrics
    prom = client.get("/api/monitoring/metrics-prom")
    assert prom.status_code == 200
    body = prom.text

    # Check presence of build info metric
    assert any(line.startswith("forge_build_info{") for line in body.splitlines())

    # Verify request counters exist and have numeric values
    total = _get_metric_value(body, "forge_request_total")
    assert total is not None and total >= 2

    exc_total = _get_metric_value(body, "forge_request_exceptions_total")
    assert exc_total is not None and exc_total >= 0

    # Histogram lines must be present with +Inf bucket, sum and count
    assert any(line.startswith("forge_request_duration_ms_bucket{le=") for line in body.splitlines())
    sum_v = _get_metric_value(body, "forge_request_duration_ms_sum")
    cnt_v = _get_metric_value(body, "forge_request_duration_ms_count")
    assert sum_v is not None and cnt_v is not None
