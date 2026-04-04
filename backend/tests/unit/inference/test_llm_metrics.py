"""Tests for backend.inference.metrics — Cost, TokenUsage, Metrics classes."""

# pylint: disable=protected-access

from __future__ import annotations

import pickle

import pytest

from backend.inference.metrics import Cost, Metrics, ResponseLatency, TokenUsage

# ── Cost dataclass ──────────────────────────────────────────────────────


class TestCost:
    def test_defaults(self):
        c = Cost()
        assert c.model == ''
        assert c.cost == 0.0
        assert c.prompt_tokens == 0
        assert isinstance(c.timestamp, float)

    def test_custom_values(self):
        c = Cost(model='gpt-4', cost=0.05, prompt_tokens=100, timestamp=1.0)
        assert c.model == 'gpt-4'
        assert c.cost == 0.05
        assert c.prompt_tokens == 100
        assert c.timestamp == 1.0


# ── ResponseLatency model ──────────────────────────────────────────────


class TestResponseLatency:
    def test_construction(self):
        rl = ResponseLatency(model='gpt-4', latency=1.5, response_id='r1')
        assert rl.model == 'gpt-4'
        assert rl.latency == 1.5
        assert rl.response_id == 'r1'


# ── TokenUsage model ───────────────────────────────────────────────────


class TestTokenUsage:
    def test_defaults(self):
        tu = TokenUsage()
        assert tu.model == ''
        assert tu.prompt_tokens == 0
        assert tu.completion_tokens == 0
        assert tu.cache_read_tokens == 0
        assert tu.cache_write_tokens == 0
        assert tu.context_window == 0
        assert tu.per_turn_token == 0
        assert tu.response_id == ''

    def test_add(self):
        a = TokenUsage(
            model='m',
            prompt_tokens=10,
            completion_tokens=5,
            context_window=100,
            per_turn_token=15,
        )
        b = TokenUsage(
            model='m',
            prompt_tokens=20,
            completion_tokens=8,
            context_window=200,
            per_turn_token=28,
        )
        result = a + b
        assert result.prompt_tokens == 30
        assert result.completion_tokens == 13
        assert result.context_window == 200  # max
        assert result.per_turn_token == 28  # other's value
        assert result.model == 'm'
        assert result.response_id == a.response_id  # from self

    def test_add_cache_tokens(self):
        a = TokenUsage(cache_read_tokens=5, cache_write_tokens=3)
        b = TokenUsage(cache_read_tokens=10, cache_write_tokens=7)
        result = a + b
        assert result.cache_read_tokens == 15
        assert result.cache_write_tokens == 10


# ── Metrics class ──────────────────────────────────────────────────────


class TestMetricsInit:
    def test_defaults(self):
        m = Metrics()
        assert m.accumulated_cost == 0.0
        assert m.max_budget_per_task is None
        assert m.costs == []
        assert m.response_latencies == []
        assert m.token_usages == []
        assert m.model_name == 'default'

    def test_custom_model(self):
        m = Metrics('claude-3')
        assert m.model_name == 'claude-3'
        assert m.accumulated_token_usage.model == 'claude-3'


class TestMetricsCostTracking:
    def test_add_cost(self):
        m = Metrics()
        m.add_cost(0.05)
        assert m.accumulated_cost == 0.05
        assert len(m.costs) == 1
        assert m.costs[0].cost == 0.05

    def test_add_cost_multiple(self):
        m = Metrics()
        m.add_cost(0.1)
        m.add_cost(0.2)
        assert m.accumulated_cost == pytest.approx(0.3)
        assert len(m.costs) == 2

    def test_add_cost_negative_raises(self):
        m = Metrics()
        with pytest.raises(ValueError, match='negative'):
            m.add_cost(-1.0)

    def test_set_accumulated_cost(self):
        m = Metrics()
        m.accumulated_cost = 5.0
        assert m.accumulated_cost == 5.0

    def test_set_accumulated_cost_negative_raises(self):
        m = Metrics()
        with pytest.raises(ValueError, match='negative'):
            m.accumulated_cost = -1.0


class TestMetricsLatency:
    def test_add_response_latency(self):
        m = Metrics('m')
        m.add_response_latency(1.5, 'r1')
        assert len(m.response_latencies) == 1
        assert m.response_latencies[0].latency == 1.5
        assert m.response_latencies[0].response_id == 'r1'

    def test_negative_latency_clamped(self):
        m = Metrics()
        m.add_response_latency(-5.0, 'r2')
        assert m.response_latencies[0].latency == 0.0


class TestMetricsTokenUsage:
    def test_add_token_usage(self):
        m = Metrics('m')
        m.add_token_usage(
            prompt_tokens=100,
            completion_tokens=50,
            cache_read_tokens=10,
            cache_write_tokens=5,
            context_window=4096,
            response_id='r1',
        )
        assert len(m.token_usages) == 1
        assert m.token_usages[0].prompt_tokens == 100
        assert m.accumulated_token_usage.prompt_tokens == 100
        assert m.accumulated_token_usage.completion_tokens == 50

    def test_add_token_usage_accumulates(self):
        m = Metrics('m')
        m.add_token_usage(
            prompt_tokens=100,
            completion_tokens=50,
            cache_read_tokens=0,
            cache_write_tokens=0,
            context_window=4096,
            response_id='r1',
        )
        m.add_token_usage(
            prompt_tokens=200,
            completion_tokens=80,
            cache_read_tokens=0,
            cache_write_tokens=0,
            context_window=8192,
            response_id='r2',
        )
        assert m.accumulated_token_usage.prompt_tokens == 300
        assert m.accumulated_token_usage.completion_tokens == 130
        assert m.accumulated_token_usage.context_window == 8192


class TestMetricsMerge:
    def test_merge_basic(self):
        m1 = Metrics('m1')
        m1.add_cost(0.1)
        m1.add_response_latency(1.0, 'r1')

        m2 = Metrics('m2')
        m2.add_cost(0.2)
        m2.add_response_latency(2.0, 'r2')

        m1.merge(m2)
        assert m1.accumulated_cost == pytest.approx(0.3)
        assert len(m1.costs) == 2
        assert len(m1.response_latencies) == 2

    def test_merge_budget_none_takes_other(self):
        m1 = Metrics()
        m2 = Metrics()
        m2.max_budget_per_task = 10.0
        m1.merge(m2)
        assert m1.max_budget_per_task == 10.0

    def test_merge_budget_existing_preserved(self):
        m1 = Metrics()
        m1.max_budget_per_task = 5.0
        m2 = Metrics()
        m2.max_budget_per_task = 10.0
        m1.merge(m2)
        assert m1.max_budget_per_task == 5.0  # existing preserved


class TestMetricsDiff:
    def test_diff_cost(self):
        baseline = Metrics('m')
        baseline.add_cost(1.0)

        current = Metrics('m')
        current._accumulated_cost = 3.0
        current._costs = baseline._costs.copy()
        # Add a new cost after baseline
        import time

        time.sleep(0.01)
        current.add_cost(2.0)

        diff = current.diff(baseline)
        assert diff.accumulated_cost == pytest.approx(
            current.accumulated_cost - baseline.accumulated_cost
        )

    def test_diff_empty_baseline(self):
        baseline = Metrics('m')
        current = Metrics('m')
        current.add_cost(1.0)
        diff = current.diff(baseline)
        assert diff.accumulated_cost == pytest.approx(1.0)
        assert len(diff.costs) == 1


class TestMetricsSerialization:
    def test_get_returns_dict(self):
        m = Metrics('m')
        m.add_cost(0.5)
        d = m.get()
        assert isinstance(d, dict)
        assert d['accumulated_cost'] == 0.5
        assert 'costs' in d
        assert 'response_latencies' in d
        assert 'token_usages' in d
        assert 'accumulated_token_usage' in d

    def test_log_returns_string(self):
        m = Metrics('m')
        result = m.log()
        assert isinstance(result, str)
        assert 'accumulated_cost' in result

    def test_repr(self):
        m = Metrics('m')
        r = repr(m)
        assert r.startswith('Metrics(')

    def test_copy_is_deep(self):
        m = Metrics('m')
        m.add_cost(1.0)
        c = m.copy()
        c.add_cost(2.0)
        assert m.accumulated_cost == pytest.approx(1.0)
        assert c.accumulated_cost == pytest.approx(3.0)

    def test_pickle_roundtrip(self):
        m = Metrics('gpt-4')
        m.add_cost(0.5)
        m.add_response_latency(1.0, 'r1')
        m.add_token_usage(100, 50, 10, 5, 4096, 'r1')

        data = pickle.dumps(m)
        restored = pickle.loads(data)

        assert restored.accumulated_cost == pytest.approx(0.5)
        assert len(restored.costs) == 1
        assert len(restored.response_latencies) == 1
        assert len(restored.token_usages) == 1
        assert restored.accumulated_token_usage.prompt_tokens == 100

    def test_getstate_setstate(self):
        m = Metrics('m')
        m.add_cost(1.0)
        state = m.__getstate__()
        assert isinstance(state, dict)

        m2 = Metrics.__new__(Metrics)
        m2.__setstate__(state)
        assert m2.accumulated_cost == pytest.approx(1.0)


class TestMetricsBudget:
    def test_set_budget(self):
        m = Metrics()
        m.max_budget_per_task = 10.0
        assert m.max_budget_per_task == 10.0

    def test_budget_default_none(self):
        m = Metrics()
        assert m.max_budget_per_task is None
