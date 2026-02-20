"""Observability middleware providing request metrics, SLO tracking, and alerting."""

from __future__ import annotations

import time
import importlib
from collections.abc import Iterable
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from backend.core.alerting import (
    AlertPolicy,
    SLOTracker,
    get_alert_client,
    get_slo_tracker,
)
from backend.core.logger import forge_logger as logger

PromCounter = Any
PromHistogram = Any

try:  # pragma: no cover - optional dependency
    _prometheus_client: Any = importlib.import_module("prometheus_client")

    _PROMETHEUS_AVAILABLE = True
except Exception:  # pragma: no cover
    _PROMETHEUS_AVAILABLE = False
    _prometheus_client = None


class RequestObservabilityMiddleware(BaseHTTPMiddleware):
    """Middleware recording HTTP request metrics with optional alerting."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        slo_tracker: SLOTracker | None = None,
        alert_policies: Iterable[AlertPolicy] | None = None,
        alerting_enabled: bool = False,
    ) -> None:
        super().__init__(app)
        self.slo_tracker = slo_tracker or get_slo_tracker()
        self.alert_policies = list(alert_policies or self._default_policies())
        self.alert_client: Any | None = get_alert_client() if alerting_enabled else None
        self.alerting_enabled = alerting_enabled
        self._request_counter: Any = None
        self._latency_histogram: Any = None
        self._setup_prometheus()

    def _setup_prometheus(self) -> None:
        if not _PROMETHEUS_AVAILABLE:
            self._request_counter = None
            self._latency_histogram = None
            return

        assert _prometheus_client is not None

        self._request_counter = _prometheus_client.Counter(
            "forge_http_requests_total",
            "Total HTTP requests handled by Forge",
            labelnames=("method", "path", "status"),
        )
        self._latency_histogram = _prometheus_client.Histogram(
            "forge_http_request_latency_seconds",
            "Latency of HTTP requests handled by Forge",
            labelnames=("method", "path", "status"),
            buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, float("inf")),
        )

    def _default_policies(self) -> list[AlertPolicy]:
        tracker = get_slo_tracker()
        return [
            AlertPolicy(
                name="availability_breach",
                metric="availability",
                threshold=tracker.availability_target,
                comparison="<",
                duration=60.0,
                enabled=True,
            ),
            AlertPolicy(
                name="latency_p95_breach",
                metric="latency_p95",
                threshold=tracker.latency_p95_target_ms,
                comparison=">",
                duration=120.0,
                enabled=True,
            ),
            AlertPolicy(
                name="error_rate_breach",
                metric="error_rate",
                threshold=tracker.error_rate_target,
                comparison=">",
                duration=60.0,
                enabled=True,
            ),
        ]

    async def dispatch(self, request: Request, call_next) -> Response:
        start_time = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception:
            # Record 500 for unhandled exceptions before re-raising
            status_code = 500
            raise
        finally:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            self._record_metrics(request, status_code, duration_ms)
            await self._maybe_alert(status_code, duration_ms)

    def _record_metrics(
        self, request: Request, status_code: int, duration_ms: float
    ) -> None:
        path_template = request.scope.get("route", None)
        path = getattr(path_template, "path", request.url.path)
        method = request.method.upper()
        status_str = str(status_code)

        if self._request_counter:
            self._request_counter.labels(method, path, status_str).inc()
        if self._latency_histogram:
            self._latency_histogram.labels(method, path, status_str).observe(
                duration_ms / 1000.0
            )

        # Record to SLO tracker
        is_error = status_code >= 500
        self.slo_tracker.record_request(duration_ms, is_error=is_error)

    async def _maybe_alert(self, status_code: int, duration_ms: float) -> None:
        if (
            not self.alerting_enabled
            or not self.alert_client
            or not self.alert_policies
        ):
            return

        metrics = self.slo_tracker.check_slo_violations()
        metrics.update(
            {
                "availability": metrics.get("availability_value", 1.0),
                "latency_p95": metrics.get("latency_p95_value", duration_ms),
                "error_rate": metrics.get("error_rate_value", 0.0),
                "last_status_code": status_code,
            }
        )

        for policy in self.alert_policies:
            value = metrics.get(policy.metric)
            if value is None:
                continue
            if policy.check(value):
                message = (
                    f"{policy.name} triggered: {policy.metric}={value:.4f} "
                    f"(threshold {policy.comparison} {policy.threshold})"
                )
                logger.warning(message)
                from backend.utils.async_utils import create_tracked_task

                create_tracked_task(
                    self.alert_client.send_alert(
                        policy_name=policy.name,
                        metric=policy.metric,
                        value=float(value),
                        threshold=policy.threshold,
                        message=message,
                    ),
                    name="observability-alert",
                )
