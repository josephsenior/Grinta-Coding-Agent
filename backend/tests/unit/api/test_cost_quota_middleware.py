"""Tests for backend.api.middleware.cost_quota — CostQuotaMiddleware."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.api.middleware.cost_quota import (
    CostQuotaMiddleware,
    DEFAULT_QUOTA_CONFIG,
    QuotaConfig,
    RedisQuotaKeys,
    _cost_store,
)


# ── Data classes ──────────────────────────────────────────────────────


class TestQuotaConfig:
    def test_dataclass_fields(self):
        cfg = QuotaConfig(daily_limit=1.0, monthly_limit=10.0, burst_limit=0.5)
        assert cfg.daily_limit == 1.0
        assert cfg.monthly_limit == 10.0
        assert cfg.burst_limit == 0.5

    def test_default_config_is_unlimited(self):
        assert DEFAULT_QUOTA_CONFIG.daily_limit == float("inf")
        assert DEFAULT_QUOTA_CONFIG.monthly_limit == float("inf")
        assert DEFAULT_QUOTA_CONFIG.burst_limit == float("inf")


class TestRedisQuotaKeys:
    def test_frozen_dataclass(self):
        keys = RedisQuotaKeys(
            daily="d", monthly="m", daily_reset="dr", monthly_reset="mr"
        )
        assert keys.daily == "d"
        assert keys.monthly == "m"
        with pytest.raises(AttributeError):
            keys.daily = "x"  # type: ignore[misc]


# ── CostQuotaMiddleware.__init__ ─────────────────────────────────────


class TestCostQuotaMiddlewareInit:
    def test_disabled_init(self):
        mw = CostQuotaMiddleware(enabled=False)
        assert mw.enabled is False

    def test_config_is_unlimited(self):
        mw = CostQuotaMiddleware(enabled=False)
        assert mw.config is DEFAULT_QUOTA_CONFIG


# ── _should_enforce_quota ────────────────────────────────────────────


class TestShouldEnforceQuota:
    def _make_request(self, path: str) -> MagicMock:
        req = MagicMock()
        req.url.path = path
        return req

    def test_disabled_returns_false(self):
        mw = CostQuotaMiddleware(enabled=False)
        req = self._make_request("/api/conversations")
        assert mw._should_enforce_quota(req) is False

    def test_exempt_path_returns_false(self):
        mw = CostQuotaMiddleware(enabled=False)
        mw.enabled = True  # bypass init side effect
        req = self._make_request("/")
        assert mw._should_enforce_quota(req) is False

    def test_normal_path_returns_true_when_enabled(self):
        mw = CostQuotaMiddleware(enabled=False)
        mw.enabled = True
        req = self._make_request("/api/conversations/start")
        assert mw._should_enforce_quota(req) is True


# ── _reset_cost_windows ─────────────────────────────────────────────


class TestResetCostWindows:
    def test_resets_daily_when_expired(self):
        mw = CostQuotaMiddleware(enabled=False)
        cost_data = {
            "daily_cost": 5.0,
            "monthly_cost": 10.0,
            "last_reset_day": time.time() - 100000,
            "last_reset_month": time.time(),
        }
        mw._reset_cost_windows(cost_data, time.time())
        assert cost_data["daily_cost"] == 0.0
        assert cost_data["monthly_cost"] == 10.0

    def test_resets_monthly_when_expired(self):
        mw = CostQuotaMiddleware(enabled=False)
        cost_data = {
            "daily_cost": 5.0,
            "monthly_cost": 10.0,
            "last_reset_day": time.time(),
            "last_reset_month": time.time() - 3000000,
        }
        mw._reset_cost_windows(cost_data, time.time())
        assert cost_data["daily_cost"] == 5.0
        assert cost_data["monthly_cost"] == 0.0

    def test_no_reset_when_recent(self):
        mw = CostQuotaMiddleware(enabled=False)
        now = time.time()
        cost_data = {
            "daily_cost": 5.0,
            "monthly_cost": 10.0,
            "last_reset_day": now,
            "last_reset_month": now,
        }
        mw._reset_cost_windows(cost_data, now + 10)
        assert cost_data["daily_cost"] == 5.0
        assert cost_data["monthly_cost"] == 10.0


# ── _within_limits ───────────────────────────────────────────────────


class TestWithinLimits:
    def test_within_limits(self):
        mw = CostQuotaMiddleware(enabled=False)
        config = QuotaConfig(daily_limit=10.0, monthly_limit=50.0, burst_limit=2.0)
        cost_data = {"daily_cost": 5.0, "monthly_cost": 20.0}
        assert mw._within_limits(cost_data, config) is True

    def test_daily_exceeded(self):
        mw = CostQuotaMiddleware(enabled=False)
        config = QuotaConfig(daily_limit=10.0, monthly_limit=50.0, burst_limit=2.0)
        cost_data = {"daily_cost": 10.0, "monthly_cost": 20.0}
        assert mw._within_limits(cost_data, config) is False

    def test_monthly_exceeded(self):
        mw = CostQuotaMiddleware(enabled=False)
        config = QuotaConfig(daily_limit=10.0, monthly_limit=50.0, burst_limit=2.0)
        cost_data = {"daily_cost": 5.0, "monthly_cost": 50.0}
        assert mw._within_limits(cost_data, config) is False

    def test_unlimited_always_within(self):
        mw = CostQuotaMiddleware(enabled=False)
        cost_data = {"daily_cost": 999999.0, "monthly_cost": 999999.0}
        assert mw._within_limits(cost_data, DEFAULT_QUOTA_CONFIG) is True


# ── record_cost ──────────────────────────────────────────────────────


class TestRecordCost:
    def setup_method(self):
        _cost_store.clear()

    def test_records_cost(self):
        mw = CostQuotaMiddleware(enabled=False)
        mw.enabled = True
        mw.record_cost("user:test-1", 1.50)
        assert _cost_store["user:test-1"]["daily_cost"] == 1.50
        assert _cost_store["user:test-1"]["monthly_cost"] == 1.50

    def test_accumulates_cost(self):
        mw = CostQuotaMiddleware(enabled=False)
        mw.enabled = True
        mw.record_cost("user:test-2", 1.0)
        mw.record_cost("user:test-2", 2.5)
        assert _cost_store["user:test-2"]["daily_cost"] == 3.5
        assert _cost_store["user:test-2"]["monthly_cost"] == 3.5

    def test_disabled_does_not_record(self):
        mw = CostQuotaMiddleware(enabled=False)
        mw.record_cost("user:noop", 10.0)
        assert "user:noop" not in _cost_store

    def teardown_method(self):
        _cost_store.clear()


# ── _get_remaining_quota ─────────────────────────────────────────────


class TestGetRemainingQuota:
    def setup_method(self):
        _cost_store.clear()

    @pytest.mark.asyncio
    async def test_full_remaining_unlimited(self):
        mw = CostQuotaMiddleware(enabled=False)
        remaining = await mw._get_remaining_quota("user:fresh")
        assert remaining["daily"] == float("inf")
        assert remaining["monthly"] == float("inf")

    @pytest.mark.asyncio
    async def test_partial_remaining_with_custom_config(self):
        mw = CostQuotaMiddleware(enabled=False)
        mw.enabled = True
        mw.config = QuotaConfig(daily_limit=10.0, monthly_limit=100.0, burst_limit=5.0)
        mw.record_cost("user:partial", 3.0)
        remaining = await mw._get_remaining_quota("user:partial")
        assert remaining["daily"] == pytest.approx(7.0)
        assert remaining["monthly"] == pytest.approx(97.0)

    @pytest.mark.asyncio
    async def test_negative_clamped_to_zero(self):
        mw = CostQuotaMiddleware(enabled=False)
        mw.enabled = True
        mw.config = QuotaConfig(daily_limit=1.0, monthly_limit=10.0, burst_limit=0.5)
        mw.record_cost("user:over", 999.0)
        remaining = await mw._get_remaining_quota("user:over")
        assert remaining["daily"] == 0.0
        assert remaining["monthly"] == 0.0

    def teardown_method(self):
        _cost_store.clear()


# ── _check_quota (async) ────────────────────────────────────────────


class TestCheckQuota:
    def setup_method(self):
        _cost_store.clear()

    @pytest.mark.asyncio
    async def test_allows_fresh_user(self):
        mw = CostQuotaMiddleware(enabled=False)
        result = await mw._check_quota("user:fresh-cq")
        assert result is True

    @pytest.mark.asyncio
    async def test_denies_over_custom_limit(self):
        mw = CostQuotaMiddleware(enabled=False)
        mw.enabled = True
        mw.config = QuotaConfig(daily_limit=5.0, monthly_limit=50.0, burst_limit=1.0)
        mw.record_cost("user:over-cq", 6.0)
        result = await mw._check_quota("user:over-cq")
        assert result is False

    def teardown_method(self):
        _cost_store.clear()


# ── __call__ (async, mock-based) ────────────────────────────────────


class TestCostQuotaCall:
    def setup_method(self):
        _cost_store.clear()

    @pytest.mark.asyncio
    async def test_disabled_passes_through(self):
        mw = CostQuotaMiddleware(enabled=False)
        req = MagicMock()
        expected_resp = MagicMock()
        call_next = AsyncMock(return_value=expected_resp)
        resp = await mw(req, call_next)
        assert resp is expected_resp

    @pytest.mark.asyncio
    async def test_passes_when_within_quota(self):
        mw = CostQuotaMiddleware(enabled=False)
        mw.enabled = True

        req = MagicMock()
        req.url.path = "/api/conversations"
        req.state.user_id = "user-ok"
        req.client.host = "127.0.0.1"
        headers_mock = MagicMock()
        headers_mock.get = MagicMock(return_value=None)
        req.headers = headers_mock

        expected_resp = MagicMock()
        expected_resp.headers = {}
        call_next = AsyncMock(return_value=expected_resp)

        await mw(req, call_next)
        call_next.assert_awaited_once()

    def teardown_method(self):
        _cost_store.clear()


# ── _get_quota_key ───────────────────────────────────────────────────


class TestGetQuotaKey:
    @pytest.mark.asyncio
    async def test_uses_user_id_when_available(self):
        mw = CostQuotaMiddleware(enabled=False)
        req = MagicMock()
        req.state.user_id = "u123"
        key = await mw._get_quota_key(req)
        assert key == "user:u123"

    @pytest.mark.asyncio
    async def test_falls_back_to_ip_hash(self):
        mw = CostQuotaMiddleware(enabled=False)
        req = MagicMock()
        req.state.user_id = None
        req.client.host = "192.168.1.1"
        headers_mock = MagicMock()
        headers_mock.get = MagicMock(return_value=None)
        req.headers = headers_mock
        key = await mw._get_quota_key(req)
        assert key.startswith("ip:")
        assert len(key) > 3

    @pytest.mark.asyncio
    async def test_uses_forwarded_for(self):
        mw = CostQuotaMiddleware(enabled=False)
        req = MagicMock()
        req.state.user_id = None
        req.client.host = "192.168.1.1"
        headers_mock = MagicMock()
        headers_mock.get = MagicMock(
            side_effect=lambda k, d=None: {
                "X-Forwarded-For": "10.0.0.1, 192.168.1.1"
            }.get(k, d)
        )
        req.headers = headers_mock
        key = await mw._get_quota_key(req)
        assert key.startswith("ip:")
