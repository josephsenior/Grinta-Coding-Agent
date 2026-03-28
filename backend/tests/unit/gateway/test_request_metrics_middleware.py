"""Tests for backend.gateway.middleware.request_metrics — _RequestMetricsRegistry."""

from __future__ import annotations

import threading


from backend.gateway.middleware.request_metrics import (
    RequestMetricsMiddleware,
    _RequestMetricsRegistry,
    get_request_metrics_snapshot,
    reset_request_metrics,
)


# ── _RequestMetricsRegistry ──────────────────────────────────────────


class TestRequestMetricsRegistry:
    def test_initial_state(self):
        reg = _RequestMetricsRegistry()
        snap = reg.snapshot()
        assert snap["request_count_total"] == 0
        assert snap["request_exceptions_total"] == 0
        assert snap["hist_sum"] == 0.0
        assert snap["hist_count"] == 0
        assert snap["in_flight"] == 0
        assert snap["request_bytes_sum"] == 0
        assert snap["response_bytes_sum"] == 0

    def test_observe_increments_count_and_sum(self):
        reg = _RequestMetricsRegistry()
        reg.observe(150.0)
        snap = reg.snapshot()
        assert snap["request_count_total"] == 1
        assert snap["hist_sum"] == 150.0
        assert snap["hist_count"] == 1

    def test_observe_places_in_correct_bucket(self):
        reg = _RequestMetricsRegistry(buckets_ms=(100, 500, 1000))
        reg.observe(75.0)  # should go in le_100
        reg.observe(250.0)  # should go in le_500
        reg.observe(999.0)  # should go in le_1000
        reg.observe(5000.0)  # should go in le_inf
        snap = reg.snapshot()
        assert snap["hist_buckets"]["le_100"] == 1
        assert snap["hist_buckets"]["le_500"] == 1
        assert snap["hist_buckets"]["le_1000"] == 1
        assert snap["hist_buckets"]["le_inf"] == 1

    def test_observe_edge_exactly_on_bucket_boundary(self):
        reg = _RequestMetricsRegistry(buckets_ms=(100, 500))
        reg.observe(100.0)  # exactly on boundary
        snap = reg.snapshot()
        assert snap["hist_buckets"]["le_100"] == 1

    def test_inc_exception(self):
        reg = _RequestMetricsRegistry()
        reg.inc_exception()
        snap = reg.snapshot()
        assert snap["request_count_total"] == 1
        assert snap["request_exceptions_total"] == 1

    def test_in_flight_tracking(self):
        reg = _RequestMetricsRegistry()
        reg.inc_in_flight()
        reg.inc_in_flight()
        assert reg.snapshot()["in_flight"] == 2
        reg.dec_in_flight()
        assert reg.snapshot()["in_flight"] == 1
        reg.dec_in_flight()
        assert reg.snapshot()["in_flight"] == 0

    def test_dec_in_flight_does_not_go_negative(self):
        reg = _RequestMetricsRegistry()
        reg.dec_in_flight()  # already 0
        assert reg.snapshot()["in_flight"] == 0

    def test_add_request_bytes(self):
        reg = _RequestMetricsRegistry()
        reg.add_request_bytes(1024)
        reg.add_request_bytes(512)
        assert reg.snapshot()["request_bytes_sum"] == 1536

    def test_add_request_bytes_ignores_negative(self):
        reg = _RequestMetricsRegistry()
        reg.add_request_bytes(-1)
        assert reg.snapshot()["request_bytes_sum"] == 0

    def test_add_response_bytes(self):
        reg = _RequestMetricsRegistry()
        reg.add_response_bytes(2048)
        assert reg.snapshot()["response_bytes_sum"] == 2048

    def test_add_response_bytes_ignores_negative(self):
        reg = _RequestMetricsRegistry()
        reg.add_response_bytes(-10)
        assert reg.snapshot()["response_bytes_sum"] == 0

    def test_reset(self):
        reg = _RequestMetricsRegistry()
        reg.observe(100.0)
        reg.inc_exception()
        reg.inc_in_flight()
        reg.add_request_bytes(1024)
        reg.add_response_bytes(2048)
        reg.reset()
        snap = reg.snapshot()
        assert snap["request_count_total"] == 0
        assert snap["request_exceptions_total"] == 0
        assert snap["in_flight"] == 0
        assert snap["request_bytes_sum"] == 0
        assert snap["response_bytes_sum"] == 0

    def test_method_status_counters(self):
        reg = _RequestMetricsRegistry()
        with reg._lock:
            reg.request_count_by_method_status[("GET", "200")] = 5
            reg.request_count_by_method_status[("POST", "404")] = 2
        snap = reg.snapshot()
        assert snap["by_method_status"]["GET:200"] == 5
        assert snap["by_method_status"]["POST:404"] == 2

    def test_route_method_status_counters(self):
        reg = _RequestMetricsRegistry()
        with reg._lock:
            reg.request_count_by_route_method_status[("GET", "200", "/api/health")] = 10
        snap = reg.snapshot()
        assert snap["by_route_method_status"]["GET|200|/api/health"] == 10

    def test_thread_safety(self):
        """Verify concurrent observations don't lose data."""
        reg = _RequestMetricsRegistry()
        n_threads = 10
        ops_per_thread = 100
        barrier = threading.Barrier(n_threads)

        def worker():
            barrier.wait()
            for _ in range(ops_per_thread):
                reg.observe(50.0)

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        snap = reg.snapshot()
        assert snap["request_count_total"] == n_threads * ops_per_thread


# ── Module-level helpers ─────────────────────────────────────────────


class TestModuleLevelHelpers:
    def test_reset_request_metrics(self):
        reset_request_metrics()
        snap = get_request_metrics_snapshot()
        assert snap["request_count_total"] == 0

    def test_snapshot_returns_dict(self):
        snap = get_request_metrics_snapshot()
        assert isinstance(snap, dict)
        assert "request_count_total" in snap


# ── RequestMetricsMiddleware ─────────────────────────────────────────


class TestRequestMetricsMiddleware:
    def test_init_enabled(self):
        mw = RequestMetricsMiddleware(enabled=True)
        assert mw.enabled is True

    def test_init_disabled(self):
        mw = RequestMetricsMiddleware(enabled=False)
        assert mw.enabled is False
