"""Tests for backend.gateway.middleware.observability."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.gateway.middleware.observability import RequestObservabilityMiddleware


async def _dummy_asgi_app(scope, receive, send):
    return None


class TestRequestObservabilityMiddleware:
    def test_setup_prometheus_uses_app_metric_names(self):
        fake_prometheus = MagicMock()

        with patch(
            "backend.gateway.middleware.observability._PROMETHEUS_AVAILABLE", True
        ), patch(
            "backend.gateway.middleware.observability._prometheus_client",
            fake_prometheus,
        ):
            RequestObservabilityMiddleware(_dummy_asgi_app)

        fake_prometheus.Counter.assert_called_once_with(
            "app_http_requests_total",
            "Total HTTP requests handled by the application",
            labelnames=("method", "path", "status"),
        )
        fake_prometheus.Histogram.assert_called_once_with(
            "app_http_request_latency_seconds",
            "Latency of HTTP requests handled by the application",
            labelnames=("method", "path", "status"),
            buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, float("inf")),
        )