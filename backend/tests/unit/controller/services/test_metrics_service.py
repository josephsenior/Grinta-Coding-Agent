"""Tests for MetricsService."""

import time
import unittest
from unittest.mock import MagicMock, patch

from backend.controller.services.metrics_service import (
    AgentMetrics,
    MetricsService,
    TaskMetrics,
)


class TestTaskMetrics(unittest.TestCase):
    """Test TaskMetrics dataclass."""

    def test_initialization(self):
        """Test TaskMetrics initializes with defaults."""
        metrics = TaskMetrics(task_id="test-task")

        self.assertEqual(metrics.task_id, "test-task")
        self.assertIsNotNone(metrics.started_at)
        self.assertIsNone(metrics.completed_at)
        self.assertIsNone(metrics.success)
        self.assertEqual(metrics.iterations_count, 0)
        self.assertEqual(metrics.error_count, 0)
        self.assertEqual(metrics.high_risk_actions, 0)
        self.assertEqual(metrics.stuck_detections, 0)
        self.assertEqual(metrics.llm_calls, 0)
        self.assertEqual(metrics.total_cost, 0.0)
        self.assertIsNone(metrics.failure_reason)

    def test_duration_seconds_not_completed(self):
        """Test duration_seconds calculates ongoing task duration."""
        started = time.time() - 5.0  # Started 5 seconds ago
        metrics = TaskMetrics(task_id="test")
        metrics.started_at = started

        duration = metrics.duration_seconds

        # Should be approximately 5 seconds
        self.assertGreater(duration, 4.9)
        self.assertLess(duration, 5.1)

    def test_duration_seconds_completed(self):
        """Test duration_seconds uses completed_at when available."""
        metrics = TaskMetrics(task_id="test")
        metrics.started_at = 100.0
        metrics.completed_at = 105.0

        duration = metrics.duration_seconds

        self.assertEqual(duration, 5.0)

    def test_success_rate_zero_iterations(self):
        """Test success_rate returns 0 with zero iterations."""
        metrics = TaskMetrics(task_id="test")

        self.assertEqual(metrics.success_rate, 0.0)

    def test_success_rate_no_errors(self):
        """Test success_rate returns 1.0 with no errors."""
        metrics = TaskMetrics(task_id="test")
        metrics.iterations_count = 10
        metrics.error_count = 0

        self.assertEqual(metrics.success_rate, 1.0)

    def test_success_rate_some_errors(self):
        """Test success_rate calculates correctly with errors."""
        metrics = TaskMetrics(task_id="test")
        metrics.iterations_count = 10
        metrics.error_count = 3

        # 1.0 - (3/10) = 0.7
        self.assertEqual(metrics.success_rate, 0.7)

    def test_success_rate_all_errors(self):
        """Test success_rate returns 0 when all iterations have errors."""
        metrics = TaskMetrics(task_id="test")
        metrics.iterations_count = 5
        metrics.error_count = 5

        self.assertEqual(metrics.success_rate, 0.0)


class TestAgentMetrics(unittest.TestCase):
    """Test AgentMetrics dataclass."""

    def test_initialization(self):
        """Test AgentMetrics initializes with zero values."""
        metrics = AgentMetrics()

        self.assertEqual(metrics.total_tasks, 0)
        self.assertEqual(metrics.successful_tasks, 0)
        self.assertEqual(metrics.failed_tasks, 0)
        self.assertEqual(metrics.total_iterations, 0)
        self.assertEqual(metrics.total_errors, 0)
        self.assertEqual(metrics.total_llm_calls, 0)
        self.assertEqual(metrics.total_cost, 0.0)
        self.assertEqual(metrics.total_duration_seconds, 0.0)

    def test_success_rate_no_tasks(self):
        """Test success_rate returns 0 with no tasks."""
        metrics = AgentMetrics()

        self.assertEqual(metrics.success_rate, 0.0)

    def test_success_rate_all_successful(self):
        """Test success_rate returns 1.0 when all tasks successful."""
        metrics = AgentMetrics()
        metrics.total_tasks = 10
        metrics.successful_tasks = 10

        self.assertEqual(metrics.success_rate, 1.0)

    def test_success_rate_partial_success(self):
        """Test success_rate calculates correctly with some failures."""
        metrics = AgentMetrics()
        metrics.total_tasks = 10
        metrics.successful_tasks = 7

        self.assertEqual(metrics.success_rate, 0.7)

    def test_average_duration_no_tasks(self):
        """Test average_duration returns 0 with no tasks."""
        metrics = AgentMetrics()

        self.assertEqual(metrics.average_duration, 0.0)

    def test_average_duration_with_tasks(self):
        """Test average_duration calculates correctly."""
        metrics = AgentMetrics()
        metrics.total_tasks = 5
        metrics.total_duration_seconds = 25.0

        self.assertEqual(metrics.average_duration, 5.0)

    def test_average_cost_no_tasks(self):
        """Test average_cost returns 0 with no tasks."""
        metrics = AgentMetrics()

        self.assertEqual(metrics.average_cost, 0.0)

    def test_average_cost_with_tasks(self):
        """Test average_cost calculates correctly."""
        metrics = AgentMetrics()
        metrics.total_tasks = 4
        metrics.total_cost = 1.2

        self.assertEqual(metrics.average_cost, 0.3)


class TestMetricsService(unittest.TestCase):
    """Test MetricsService tracking logic."""

    def setUp(self):
        """Create mock context for testing."""
        self.mock_context = MagicMock()
        self.service = MetricsService(self.mock_context)

    @patch("backend.controller.services.metrics_service.logger")
    def test_start_task(self, mock_logger):
        """Test start_task creates new TaskMetrics."""
        self.service.start_task("task-123")

        self.assertIsNotNone(self.service._current_task)
        self.assertEqual(self.service._current_task.task_id, "task-123")
        mock_logger.info.assert_called_once()

    def test_record_iteration(self):
        """Test record_iteration increments counter."""
        self.service.start_task("test")

        self.service.record_iteration()
        self.assertEqual(self.service._current_task.iterations_count, 1)

        self.service.record_iteration()
        self.assertEqual(self.service._current_task.iterations_count, 2)

    def test_record_iteration_no_active_task(self):
        """Test record_iteration does nothing without active task."""
        # Should not raise exception
        self.service.record_iteration()

    def test_record_error(self):
        """Test record_error increments counter."""
        self.service.start_task("test")

        self.service.record_error()
        self.assertEqual(self.service._current_task.error_count, 1)

    def test_record_high_risk_action(self):
        """Test record_high_risk_action increments counter."""
        self.service.start_task("test")

        self.service.record_high_risk_action()
        self.assertEqual(self.service._current_task.high_risk_actions, 1)

    def test_record_stuck_detection(self):
        """Test record_stuck_detection increments counter."""
        self.service.start_task("test")

        self.service.record_stuck_detection()
        self.assertEqual(self.service._current_task.stuck_detections, 1)

    def test_record_llm_call_no_cost(self):
        """Test record_llm_call increments call counter."""
        self.service.start_task("test")

        self.service.record_llm_call()
        self.assertEqual(self.service._current_task.llm_calls, 1)
        self.assertEqual(self.service._current_task.total_cost, 0.0)

    def test_record_llm_call_with_cost(self):
        """Test record_llm_call accumulates cost."""
        self.service.start_task("test")

        self.service.record_llm_call(cost=0.5)
        self.service.record_llm_call(cost=0.3)

        self.assertEqual(self.service._current_task.llm_calls, 2)
        self.assertAlmostEqual(self.service._current_task.total_cost, 0.8)

    @patch("backend.controller.services.metrics_service.logger")
    def test_complete_task_success(self, mock_logger):
        """Test complete_task marks task as successful and updates aggregate."""
        self.service.start_task("test-task")
        self.service.record_iteration()
        self.service.record_llm_call(cost=0.25)

        completed = self.service.complete_task(success=True)

        self.assertEqual(completed.task_id, "test-task")
        self.assertTrue(completed.success)
        self.assertIsNotNone(completed.completed_at)
        self.assertIsNone(completed.failure_reason)

        # Check aggregate updated
        self.assertEqual(self.service._aggregate.total_tasks, 1)
        self.assertEqual(self.service._aggregate.successful_tasks, 1)
        self.assertEqual(self.service._aggregate.failed_tasks, 0)

    @patch("backend.controller.services.metrics_service.logger")
    def test_complete_task_failure(self, mock_logger):
        """Test complete_task marks task as failed with reason."""
        self.service.start_task("test-task")

        completed = self.service.complete_task(success=False, failure_reason="Timeout")

        self.assertFalse(completed.success)
        self.assertEqual(completed.failure_reason, "Timeout")

        # Check aggregate updated
        self.assertEqual(self.service._aggregate.total_tasks, 1)
        self.assertEqual(self.service._aggregate.successful_tasks, 0)
        self.assertEqual(self.service._aggregate.failed_tasks, 1)

    @patch("backend.controller.services.metrics_service.logger")
    def test_complete_task_no_active_task(self, mock_logger):
        """Test complete_task handles no active task gracefully."""
        completed = self.service.complete_task(success=False)

        self.assertEqual(completed.task_id, "unknown")
        self.assertFalse(completed.success)
        mock_logger.warning.assert_called_once()

    @patch("backend.controller.services.metrics_service.logger")
    def test_complete_task_updates_aggregate_metrics(self, mock_logger):
        """Test complete_task updates all aggregate metrics."""
        self.service.start_task("test")
        self.service.record_iteration()
        self.service.record_iteration()
        self.service.record_error()
        self.service.record_llm_call(cost=0.5)
        self.service.record_llm_call(cost=0.3)

        # Simulate some duration
        self.service._current_task.started_at = time.time() - 10.0

        self.service.complete_task(success=True)

        agg = self.service._aggregate
        self.assertEqual(agg.total_iterations, 2)
        self.assertEqual(agg.total_errors, 1)
        self.assertEqual(agg.total_llm_calls, 2)
        self.assertAlmostEqual(agg.total_cost, 0.8)
        self.assertGreater(agg.total_duration_seconds, 9.0)

    @patch("backend.controller.services.metrics_service.logger")
    def test_complete_task_clears_current_task(self, mock_logger):
        """Test complete_task clears current task."""
        self.service.start_task("test")
        self.service.complete_task(success=True)

        self.assertIsNone(self.service._current_task)

    def test_get_current_task_metrics(self):
        """Test get_current_task_metrics returns current task."""
        self.assertIsNone(self.service.get_current_task_metrics())

        self.service.start_task("test")
        current = self.service.get_current_task_metrics()

        self.assertIsNotNone(current)
        self.assertEqual(current.task_id, "test")

    def test_get_aggregate_metrics(self):
        """Test get_aggregate_metrics returns aggregate."""
        aggregate = self.service.get_aggregate_metrics()

        self.assertIsInstance(aggregate, AgentMetrics)
        self.assertEqual(aggregate.total_tasks, 0)

    @patch("backend.controller.services.metrics_service.logger")
    def test_reset(self, mock_logger):
        """Test reset clears all metrics."""
        self.service.start_task("test")
        self.service.record_iteration()
        self.service.complete_task(success=True)

        self.service.reset()

        self.assertIsNone(self.service._current_task)
        self.assertEqual(self.service._aggregate.total_tasks, 0)
        mock_logger.info.assert_called()  # At least 2 calls (start_task, reset)

    @patch("backend.controller.services.metrics_service.logger")
    def test_multiple_tasks_workflow(self, mock_logger):
        """Test complete workflow with multiple tasks."""
        # Task 1: Success
        self.service.start_task("task-1")
        self.service.record_iteration()
        self.service.record_llm_call(cost=0.1)
        self.service.complete_task(success=True)

        # Task 2: Failure
        self.service.start_task("task-2")
        self.service.record_iteration()
        self.service.record_error()
        self.service.complete_task(success=False, failure_reason="Error")

        # Task 3: Success
        self.service.start_task("task-3")
        self.service.record_llm_call(cost=0.2)
        self.service.complete_task(success=True)

        agg = self.service._aggregate
        self.assertEqual(agg.total_tasks, 3)
        self.assertEqual(agg.successful_tasks, 2)
        self.assertEqual(agg.failed_tasks, 1)
        self.assertEqual(agg.success_rate, 2 / 3)


if __name__ == "__main__":
    unittest.main()
