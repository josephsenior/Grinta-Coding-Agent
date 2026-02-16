"""Unit tests for backend.core.alerting — AlertPolicy, SLOTracker."""

from __future__ import annotations

import time

import pytest

from backend.core.alerting import AlertPolicy, SLOTracker


# ---------------------------------------------------------------------------
# AlertPolicy
# ---------------------------------------------------------------------------


class TestAlertPolicy:
    def test_disabled_never_fires(self):
        p = AlertPolicy("test", "cpu", 0.9, enabled=False)
        assert p.check(1.0) is False
        assert p.check(999.0) is False

    def test_below_threshold_no_fire(self):
        p = AlertPolicy("test", "cpu", 0.9, comparison=">", duration=0.0)
        assert p.check(0.5) is False

    def test_threshold_comparison_gt(self):
        p = AlertPolicy("test", "cpu", 0.9, comparison=">", duration=0.0)
        # First call starts violation timer
        p.check(0.95)
        # Violation start is set but duration not passed yet (though we set 0,
        # the implementation first returns False on the very first check)
        # We need a second call once violation_start is set
        time.sleep(0.01)
        assert p.check(0.95) is True

    def test_threshold_comparison_lt(self):
        p = AlertPolicy("test", "mem", 0.1, comparison="<", duration=0.0)
        p.check(0.05)
        time.sleep(0.01)
        assert p.check(0.05) is True

    def test_threshold_comparison_gte(self):
        p = AlertPolicy("test", "x", 10.0, comparison=">=", duration=0.0)
        p.check(10.0)
        time.sleep(0.01)
        assert p.check(10.0) is True

    def test_threshold_comparison_lte(self):
        p = AlertPolicy("test", "x", 10.0, comparison="<=", duration=0.0)
        p.check(10.0)
        time.sleep(0.01)
        assert p.check(10.0) is True

    def test_threshold_comparison_eq(self):
        p = AlertPolicy("test", "x", 10.0, comparison="==", duration=0.0)
        p.check(10.0)
        time.sleep(0.01)
        assert p.check(10.0) is True

    def test_recovery_resets(self):
        p = AlertPolicy("test", "cpu", 0.9, comparison=">", duration=0.0)
        p.check(0.95)  # start violation
        p.check(0.5)   # drops below → resets
        assert p._violation_start_time is None

    def test_cooldown(self):
        p = AlertPolicy("test", "cpu", 0.9, comparison=">", duration=0.0)
        p._alert_cooldown = 300.0
        p.check(0.95)
        time.sleep(0.01)
        assert p.check(0.95) is True  # first alert
        # Now within cooldown
        p.check(0.95)
        time.sleep(0.01)
        assert p.check(0.95) is False  # cooldown active

    def test_reset(self):
        p = AlertPolicy("test", "cpu", 0.9, comparison=">", duration=0.0)
        p._violation_start_time = time.time()
        p._last_alert_time = time.time()
        p.reset()
        assert p._violation_start_time is None
        assert p._last_alert_time is None


# ---------------------------------------------------------------------------
# SLOTracker
# ---------------------------------------------------------------------------


class TestSLOTracker:
    def test_defaults(self):
        slo = SLOTracker()
        assert slo.availability_target == 0.99
        assert slo.latency_p95_target_ms == 1000.0
        assert slo.error_rate_target == 0.01

    def test_availability_no_requests(self):
        slo = SLOTracker()
        assert slo.get_availability() == 1.0

    def test_availability_all_success(self):
        slo = SLOTracker()
        for _ in range(10):
            slo.record_request(50.0, is_error=False)
        assert slo.get_availability() == 1.0

    def test_availability_some_errors(self):
        slo = SLOTracker()
        for _ in range(8):
            slo.record_request(50.0)
        for _ in range(2):
            slo.record_request(50.0, is_error=True)
        assert slo.get_availability() == pytest.approx(0.8)

    def test_error_rate_no_requests(self):
        slo = SLOTracker()
        assert slo.get_error_rate() == 0.0

    def test_error_rate(self):
        slo = SLOTracker()
        slo.record_request(10.0, is_error=False)
        slo.record_request(10.0, is_error=True)
        assert slo.get_error_rate() == pytest.approx(0.5)

    def test_latency_p95_no_samples(self):
        slo = SLOTracker()
        assert slo.get_latency_p95() == 0.0

    def test_latency_p95(self):
        slo = SLOTracker()
        # Add 100 samples: [1, 2, ..., 100]
        for i in range(1, 101):
            slo.record_request(float(i))
        p95 = slo.get_latency_p95()
        assert p95 >= 95.0  # should be around 95-96

    def test_check_slo_violations_none(self):
        slo = SLOTracker()
        for _ in range(100):
            slo.record_request(10.0)
        v = slo.check_slo_violations()
        assert v["availability"] is False
        assert v["error_rate"] is False
        assert v["latency"] is False

    def test_check_slo_violations_all_bad(self):
        slo = SLOTracker(availability_target=0.99, error_rate_target=0.01, latency_p95_target_ms=10.0)
        for _ in range(50):
            slo.record_request(100.0, is_error=True)
        v = slo.check_slo_violations()
        assert v["availability"] is True
        assert v["error_rate"] is True
        assert v["latency"] is True

    def test_custom_targets(self):
        slo = SLOTracker(availability_target=0.5, latency_p95_target_ms=500.0, error_rate_target=0.5)
        assert slo.availability_target == 0.5
        assert slo.latency_p95_target_ms == 500.0
        assert slo.error_rate_target == 0.5
