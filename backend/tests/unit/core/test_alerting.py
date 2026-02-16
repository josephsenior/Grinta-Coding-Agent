"""Unit tests for backend.core.alerting — AlertPolicy, SLOTracker."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import urlparse

import pytest

from backend.core.alerting import (
    AlertManager,
    AlertPolicy,
    SLOTracker,
    get_alert_manager,
    get_alert_client,
    get_slo_tracker,
)


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

    def test_unknown_comparison_never_violates(self):
        p = AlertPolicy("test", "cpu", 0.9, comparison="!=", duration=0.0)
        assert p.check(1.0) is False

    def test_duration_not_met(self, monkeypatch):
        p = AlertPolicy("test", "cpu", 0.9, comparison=">", duration=10.0)
        t = [100.0]

        monkeypatch.setattr(time, "time", lambda: t[0])
        p.check(0.95)
        t[0] += 1.0
        assert p.check(0.95) is False


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

    def test_window_reset_on_expiry(self, monkeypatch):
        slo = SLOTracker()
        slo._request_count = 5
        slo._error_count = 2
        slo._latency_samples = [1.0]

        now = [100.0]
        monkeypatch.setattr(time, "time", lambda: now[0])
        slo._window_start_time = 0.0
        now[0] = 1000.0

        slo.record_request(10.0, is_error=False)

        assert slo._request_count == 0
        assert slo._error_count == 0
        assert len(slo._latency_samples) == 0


class TestAlertManager:
    def test_build_payload_variants(self):
        mgr = AlertManager(endpoint="http://x", api_key="k", enabled=True)
        parsed = urlparse("https://events.pagerduty.com/v2/enqueue")
        payload = mgr._build_payload(parsed, "p", "m", 1.0, 2.0, "msg")
        assert "routing_key" in payload

        parsed = urlparse("https://hooks.slack.com/services/abc")
        payload = mgr._build_payload(parsed, "p", "m", 1.0, 2.0, None)
        assert payload["text"].startswith("Alert:")

        parsed = urlparse("https://example.com/alert")
        payload = mgr._build_payload(parsed, "p", "m", 1.0, 2.0, None)
        assert payload["metric"] == "m"

    @pytest.mark.asyncio
    async def test_execute_alert_request_success(self):
        mgr = AlertManager(endpoint="http://x", enabled=True)

        class FakeResponse:
            status = 200

            async def text(self):
                return "ok"

        class FakeContext:
            def __init__(self, response):
                self._response = response

            async def __aenter__(self):
                return self._response

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class FakeSession:
            def post(self, *args, **kwargs):
                return FakeContext(FakeResponse())

        result = await mgr._execute_alert_request(
            FakeSession(), {"X": "Y"}, {"p": 1}, "p", "m", 1.0
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_execute_alert_request_failure(self):
        mgr = AlertManager(endpoint="http://x", enabled=True)

        class FakeResponse:
            status = 500

            async def text(self):
                return "fail"

        class FakeContext:
            def __init__(self, response):
                self._response = response

            async def __aenter__(self):
                return self._response

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class FakeSession:
            def post(self, *args, **kwargs):
                return FakeContext(FakeResponse())

        result = await mgr._execute_alert_request(
            FakeSession(), {"X": "Y"}, {"p": 1}, "p", "m", 1.0
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_send_alert_calls_send_request(self):
        mgr = AlertManager(endpoint="http://x", enabled=True)
        with patch.object(mgr, "_send_request", new=AsyncMock(return_value=True)) as send_mock:
            result = await mgr.send_alert("p", "m", 1.0, 2.0, message="hi")
        assert result is True
        assert send_mock.called

    @pytest.mark.asyncio
    async def test_shutdown_closes_session(self):
        mgr = AlertManager(endpoint="http://x", enabled=True)
        mgr._session = MagicMock()
        mgr._session.closed = False
        mgr._session.close = AsyncMock()
        await mgr.shutdown()
        mgr._session.close.assert_awaited_once()


class TestAlertingGlobals:
    def test_get_alert_manager_configured(self, monkeypatch):
        monkeypatch.setenv("ALERTING_ENDPOINT", "http://x")
        monkeypatch.setenv("ALERTING_API_KEY", "k")
        monkeypatch.setenv("ALERTING_ENABLED", "true")

        import backend.core.alerting as alerting

        alerting._alert_manager = None
        mgr = get_alert_manager()
        assert mgr is not None
        assert get_alert_client() is mgr

    def test_get_alert_manager_disabled(self, monkeypatch):
        monkeypatch.setenv("ALERTING_ENABLED", "false")
        monkeypatch.delenv("ALERTING_ENDPOINT", raising=False)

        import backend.core.alerting as alerting

        alerting._alert_manager = None
        mgr = get_alert_manager()
        assert mgr is None

    def test_get_slo_tracker_env(self, monkeypatch):
        monkeypatch.setenv("SLO_AVAILABILITY_TARGET", "0.9")
        monkeypatch.setenv("SLO_LATENCY_P95_TARGET_MS", "500")
        monkeypatch.setenv("SLO_ERROR_RATE_TARGET", "0.02")

        import backend.core.alerting as alerting

        alerting._slo_tracker = None
        slo = get_slo_tracker()
        assert slo.availability_target == 0.9
        assert slo.latency_p95_target_ms == 500.0
        assert slo.error_rate_target == 0.02
