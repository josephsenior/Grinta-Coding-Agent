"""Lightweight request metrics middleware and in-process registry.

Collects total request count, exception count, and a latency histogram in ms.
Exposed via the monitoring "/metrics-prom" endpoint.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from fastapi import Request, Response

# Default histogram buckets in milliseconds
_DEFAULT_BUCKETS_MS: tuple[int, ...] = (
    50,
    100,
    250,
    500,
    1000,
    2500,
    5000,
    10000,
)


class _RequestMetricsRegistry:
    def __init__(self, buckets_ms: tuple[int, ...] = _DEFAULT_BUCKETS_MS) -> None:
        self._lock = threading.Lock()
        self._buckets = buckets_ms
        self._in_flight = 0
        self._reset()

    def _reset(self) -> None:
        self.request_count_total = 0
        self.request_exceptions_total = 0
        self.request_duration_ms_sum = 0.0
        self.request_duration_ms_count = 0
        # Store counts for le_{bucket}
        self.request_duration_ms_buckets = {f"le_{b}": 0 for b in self._buckets}
        # Special +Inf bucket stored under key le_inf for convenience
        self.request_duration_ms_buckets["le_inf"] = 0
        self._in_flight = 0
        # Byte counters
        self.request_bytes_sum = 0
        self.response_bytes_sum = 0
        # Method/Status counters
        self.request_count_by_method_status: dict[tuple[str, str], int] = {}
        # Method/Status/Route counters (route path template if available)
        self.request_count_by_route_method_status: dict[tuple[str, str, str], int] = {}

    def reset(self) -> None:
        with self._lock:
            self._reset()

    def observe(self, duration_ms: float) -> None:
        with self._lock:
            self.request_count_total += 1
            self.request_duration_ms_sum += duration_ms
            self.request_duration_ms_count += 1
            placed = False
            for b in self._buckets:
                if duration_ms <= b:
                    self.request_duration_ms_buckets[f"le_{b}"] += 1
                    placed = True
                    break
            if not placed:
                self.request_duration_ms_buckets["le_inf"] += 1

    def inc_exception(self) -> None:
        with self._lock:
            self.request_count_total += 1
            self.request_exceptions_total += 1
            # Exception requests also counted in total with no duration observation

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "request_count_total": self.request_count_total,
                "request_exceptions_total": self.request_exceptions_total,
                "hist_buckets": dict(self.request_duration_ms_buckets),
                "hist_sum": self.request_duration_ms_sum,
                "hist_count": self.request_duration_ms_count,
                "in_flight": self._in_flight,
                "request_bytes_sum": self.request_bytes_sum,
                "response_bytes_sum": self.response_bytes_sum,
                "by_method_status": {
                    f"{m}:{s}": c
                    for (m, s), c in self.request_count_by_method_status.items()
                },
                "by_route_method_status": {
                    f"{m}|{s}|{r}": c
                    for (
                        m,
                        s,
                        r,
                    ), c in self.request_count_by_route_method_status.items()
                },
            }

    def inc_in_flight(self) -> None:
        with self._lock:
            self._in_flight += 1

    def dec_in_flight(self) -> None:
        with self._lock:
            if self._in_flight > 0:
                self._in_flight -= 1

    def add_request_bytes(self, size: int) -> None:
        if size < 0:
            return
        with self._lock:
            self.request_bytes_sum += size

    def add_response_bytes(self, size: int) -> None:
        if size < 0:
            return
        with self._lock:
            self.response_bytes_sum += size


_request_metrics_registry = _RequestMetricsRegistry()


def reset_request_metrics() -> None:
    _request_metrics_registry.reset()


def get_request_metrics_snapshot() -> dict[str, Any]:
    return _request_metrics_registry.snapshot()


class RequestMetricsMiddleware:
    """ASGI middleware to collect request metrics."""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    async def __call__(self, request: Request, call_next: Callable) -> Response:
        if not self.enabled:
            return await call_next(request)

        start = time.perf_counter()
        _request_metrics_registry.inc_in_flight()
        self._record_request_size(request)
        try:
            response = await call_next(request)
        except Exception:
            self._record_exception_metrics(request)
            _request_metrics_registry.dec_in_flight()
            raise

        self._record_success_metrics(request, response, start)
        _request_metrics_registry.dec_in_flight()
        return response

    def _record_request_size(self, request: Request) -> None:
        try:
            if "content-length" in request.headers:
                _request_metrics_registry.add_request_bytes(
                    int(request.headers.get("content-length", "0"))
                )
        except Exception:
            pass

    def _record_exception_metrics(self, request: Request) -> None:
        _request_metrics_registry.inc_exception()
        self._increment_method_status(
            request.method.upper(),
            "exception",
            self._route_path(request),
        )

    def _record_success_metrics(
        self,
        request: Request,
        response: Response,
        start_time: float,
    ) -> None:
        duration_ms = (time.perf_counter() - start_time) * 1000.0
        _request_metrics_registry.observe(duration_ms)
        self._record_response_size(response)
        self._increment_method_status(
            request.method.upper(),
            str(response.status_code),
            self._route_path(request),
        )

    def _record_response_size(self, response: Response) -> None:
        try:
            if "content-length" in response.headers:
                _request_metrics_registry.add_response_bytes(
                    int(response.headers.get("content-length", "0"))
                )
                return
        except Exception:
            pass

        body = getattr(response, "body", None)
        if isinstance(body, (bytes, bytearray)):
            _request_metrics_registry.add_response_bytes(len(body))

    def _increment_method_status(
        self,
        method: str,
        status: str,
        route_path: str,
    ) -> None:
        try:
            with _request_metrics_registry._lock:
                key = (method, status)
                _request_metrics_registry.request_count_by_method_status[key] = (
                    _request_metrics_registry.request_count_by_method_status.get(key, 0)
                    + 1
                )
                rkey = (method, status, route_path)
                _request_metrics_registry.request_count_by_route_method_status[rkey] = (
                    _request_metrics_registry.request_count_by_route_method_status.get(
                        rkey, 0
                    )
                    + 1
                )
        except Exception:
            pass

    def _route_path(self, request: Request) -> str:
        try:
            route = request.scope.get("route") if hasattr(request, "scope") else None
            if route and getattr(route, "path", None):
                return route.path
        except Exception:
            pass
        return request.url.path
