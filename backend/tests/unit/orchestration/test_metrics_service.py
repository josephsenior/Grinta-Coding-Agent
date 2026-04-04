"""Unit tests for backend.orchestration.services.metrics_service."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from backend.orchestration.services.metrics_service import (
    AgentMetrics,
    MetricsService,
    TaskMetrics,
)

# ---------------------------------------------------------------------------
# TaskMetrics dataclass
# ---------------------------------------------------------------------------


class TestTaskMetrics:
    def test_defaults(self):
        tm = TaskMetrics(task_id='t1')
        assert tm.task_id == 't1'
        assert tm.iterations_count == 0
        assert tm.error_count == 0
        assert tm.success is None

    def test_duration_running(self):
        tm = TaskMetrics(task_id='t', started_at=time.time() - 10)
        assert tm.duration_seconds >= 9.5

    def test_duration_completed(self):
        tm = TaskMetrics(task_id='t', started_at=100.0, completed_at=110.0)
        assert tm.duration_seconds == pytest.approx(10.0)

    def test_success_rate_no_iterations(self):
        tm = TaskMetrics(task_id='t')
        assert tm.success_rate == 0.0

    def test_success_rate_all_good(self):
        tm = TaskMetrics(task_id='t', iterations_count=10, error_count=0)
        assert tm.success_rate == 1.0

    def test_success_rate_half_errors(self):
        tm = TaskMetrics(task_id='t', iterations_count=10, error_count=5)
        assert tm.success_rate == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# AgentMetrics dataclass
# ---------------------------------------------------------------------------


class TestAgentMetrics:
    def test_defaults(self):
        am = AgentMetrics()
        assert am.total_tasks == 0
        assert am.success_rate == 0.0
        assert am.average_duration == 0.0
        assert am.average_cost == 0.0

    def test_success_rate(self):
        am = AgentMetrics(total_tasks=10, successful_tasks=7)
        assert am.success_rate == pytest.approx(0.7)

    def test_average_duration(self):
        am = AgentMetrics(total_tasks=4, total_duration_seconds=100.0)
        assert am.average_duration == pytest.approx(25.0)

    def test_average_cost(self):
        am = AgentMetrics(total_tasks=5, total_cost=2.5)
        assert am.average_cost == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# MetricsService
# ---------------------------------------------------------------------------


class TestMetricsService:
    @pytest.fixture()
    def ctx(self):
        return MagicMock()

    @pytest.fixture()
    def svc(self, ctx):
        return MetricsService(ctx)

    def test_initial_no_task(self, svc):
        assert svc.get_current_task_metrics() is None

    def test_start_task(self, svc):
        svc.start_task('task-1')
        current = svc.get_current_task_metrics()
        assert current is not None
        assert current.task_id == 'task-1'

    def test_record_iteration(self, svc):
        svc.start_task('t')
        svc.record_iteration()
        svc.record_iteration()
        assert svc.get_current_task_metrics().iterations_count == 2

    def test_record_error(self, svc):
        svc.start_task('t')
        svc.record_error()
        assert svc.get_current_task_metrics().error_count == 1

    def test_record_high_risk_action(self, svc):
        svc.start_task('t')
        svc.record_high_risk_action()
        assert svc.get_current_task_metrics().high_risk_actions == 1

    def test_record_stuck_detection(self, svc):
        svc.start_task('t')
        svc.record_stuck_detection()
        assert svc.get_current_task_metrics().stuck_detections == 1

    def test_record_llm_call(self, svc):
        svc.start_task('t')
        svc.record_llm_call(cost=0.05)
        svc.record_llm_call(cost=0.10)
        current = svc.get_current_task_metrics()
        assert current.llm_calls == 2
        assert current.total_cost == pytest.approx(0.15)

    def test_complete_task_success(self, svc):
        svc.start_task('t1')
        svc.record_iteration()
        result = svc.complete_task(success=True)
        assert result.success is True
        assert result.completed_at is not None
        assert svc.get_current_task_metrics() is None

        agg = svc.get_aggregate_metrics()
        assert agg.total_tasks == 1
        assert agg.successful_tasks == 1
        assert agg.failed_tasks == 0

    def test_complete_task_failure(self, svc):
        svc.start_task('t2')
        result = svc.complete_task(success=False, failure_reason='timeout')
        assert result.success is False
        assert result.failure_reason == 'timeout'

        agg = svc.get_aggregate_metrics()
        assert agg.failed_tasks == 1

    def test_complete_no_active_task(self, svc):
        result = svc.complete_task(success=False)
        assert result.task_id == 'unknown'

    def test_aggregate_across_tasks(self, svc):
        svc.start_task('a')
        svc.record_llm_call(cost=0.01)
        svc.record_iteration()
        svc.complete_task(success=True)

        svc.start_task('b')
        svc.record_llm_call(cost=0.02)
        svc.record_iteration()
        svc.record_error()
        svc.complete_task(success=False)

        agg = svc.get_aggregate_metrics()
        assert agg.total_tasks == 2
        assert agg.total_llm_calls == 2
        assert agg.total_cost == pytest.approx(0.03)
        assert agg.total_iterations == 2
        assert agg.total_errors == 1
        assert agg.success_rate == pytest.approx(0.5)

    def test_reset(self, svc):
        svc.start_task('t')
        svc.record_iteration()
        svc.complete_task(success=True)
        svc.reset()
        assert svc.get_current_task_metrics() is None
        assert svc.get_aggregate_metrics().total_tasks == 0

    def test_record_on_no_active_task_is_noop(self, svc):
        # Should not raise
        svc.record_iteration()
        svc.record_error()
        svc.record_high_risk_action()
        svc.record_stuck_detection()
        svc.record_llm_call(cost=1.0)
