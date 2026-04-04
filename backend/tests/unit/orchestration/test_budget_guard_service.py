"""Unit tests for backend.orchestration.services.budget_guard_service."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock

from backend.orchestration.services.budget_guard_service import (
    _BUDGET_THRESHOLDS,
    BudgetGuardService,
)
from backend.orchestration.services.orchestration_context import OrchestrationContext


class _FakeContext:
    id: str
    state: SimpleNamespace | None
    state_tracker: object | None
    events: list[tuple[MagicMock, object]]

    def __init__(self, current: float, max_value: float):
        self.id = 'sess-1'
        budget_flag = SimpleNamespace(current_value=current, max_value=max_value)
        self.state = SimpleNamespace(budget_flag=budget_flag)
        self.state_tracker = None
        self.events: list = []

    def emit_event(self, event, source):
        self.events.append((event, source))


class TestBudgetGuardService:
    def test_no_alert_below_threshold(self):
        ctx = _FakeContext(current=0.10, max_value=1.00)  # 10%
        svc = BudgetGuardService(cast(OrchestrationContext, ctx))
        svc._check_budget_thresholds()
        assert not svc._alerted_thresholds

    def test_alert_at_50_percent(self):
        ctx = _FakeContext(current=0.55, max_value=1.00)
        svc = BudgetGuardService(cast(OrchestrationContext, ctx))
        svc._check_budget_thresholds()
        assert 0.50 in svc._alerted_thresholds
        assert 0.80 not in svc._alerted_thresholds

    def test_alert_at_90_percent(self):
        ctx = _FakeContext(current=0.95, max_value=1.00)
        svc = BudgetGuardService(cast(OrchestrationContext, ctx))
        svc._check_budget_thresholds()
        # All three thresholds should fire
        assert svc._alerted_thresholds == {0.50, 0.80, 0.90}

    def test_each_threshold_fires_once(self):
        ctx = _FakeContext(current=0.95, max_value=1.00)
        svc = BudgetGuardService(cast(OrchestrationContext, ctx))
        svc._check_budget_thresholds()
        count_1 = len(ctx.events)
        svc._check_budget_thresholds()  # call again
        assert len(ctx.events) == count_1  # no new events

    def test_no_state(self):
        ctx = _FakeContext(current=0, max_value=1.0)
        ctx.state = None
        svc = BudgetGuardService(cast(OrchestrationContext, ctx))
        svc._check_budget_thresholds()  # should not raise

    def test_no_budget_flag(self):
        ctx = _FakeContext(current=0, max_value=1.0)
        ctx.state = SimpleNamespace(budget_flag=None)
        svc = BudgetGuardService(cast(OrchestrationContext, ctx))
        svc._check_budget_thresholds()  # should not raise

    def test_max_value_zero(self):
        ctx = _FakeContext(current=0, max_value=1.0)
        ctx.state = SimpleNamespace(
            budget_flag=SimpleNamespace(current_value=5, max_value=0)
        )
        svc = BudgetGuardService(cast(OrchestrationContext, ctx))
        svc._check_budget_thresholds()  # no div-by-zero
        assert not svc._alerted_thresholds

    def test_sync_with_metrics_calls_state_tracker(self):
        ctx = _FakeContext(current=0.1, max_value=1.0)
        tracker = MagicMock()
        ctx.state_tracker = tracker
        svc = BudgetGuardService(cast(OrchestrationContext, ctx))
        svc.sync_with_metrics()
        tracker.sync_budget_flag_with_metrics.assert_called_once()

    def test_emit_budget_alert_content(self):
        ctx = _FakeContext(current=0.85, max_value=1.00)
        svc = BudgetGuardService(cast(OrchestrationContext, ctx))
        svc._check_budget_thresholds()
        # Should have alerts for 50% and 80%
        assert len(ctx.events) >= 2
        # Check that the event content mentions budget
        for event, _source in ctx.events:
            assert 'budget' in event.content.lower() or 'Budget' in event.content

    def test_thresholds_are_sorted(self):
        assert list(_BUDGET_THRESHOLDS) == sorted(_BUDGET_THRESHOLDS)
