"""Agent performance metrics tracking service."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from backend.core.logger import forge_logger as logger

if TYPE_CHECKING:
    from backend.orchestration.services.orchestration_context import OrchestrationContext


@dataclass
class TaskMetrics:
    """Metrics for a single task execution."""

    task_id: str
    started_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    success: bool | None = None
    iterations_count: int = 0
    error_count: int = 0
    high_risk_actions: int = 0
    stuck_detections: int = 0
    llm_calls: int = 0
    total_cost: float = 0.0
    failure_reason: str | None = None

    @property
    def duration_seconds(self) -> float:
        """Calculate task duration in seconds."""
        end_time = self.completed_at or time.time()
        return end_time - self.started_at

    @property
    def success_rate(self) -> float:
        """Calculate success rate (iterations without errors / total iterations)."""
        if self.iterations_count == 0:
            return 0.0
        return 1.0 - (self.error_count / self.iterations_count)


@dataclass
class AgentMetrics:
    """Aggregate metrics across all tasks."""

    total_tasks: int = 0
    successful_tasks: int = 0
    failed_tasks: int = 0
    total_iterations: int = 0
    total_errors: int = 0
    total_llm_calls: int = 0
    total_cost: float = 0.0
    total_duration_seconds: float = 0.0

    @property
    def success_rate(self) -> float:
        """Overall task success rate."""
        if self.total_tasks == 0:
            return 0.0
        return self.successful_tasks / self.total_tasks

    @property
    def average_duration(self) -> float:
        """Average task duration in seconds."""
        if self.total_tasks == 0:
            return 0.0
        return self.total_duration_seconds / self.total_tasks

    @property
    def average_cost(self) -> float:
        """Average cost per task."""
        if self.total_tasks == 0:
            return 0.0
        return self.total_cost / self.total_tasks


class MetricsService:
    """Tracks agent performance metrics."""

    def __init__(self, context: OrchestrationContext) -> None:
        self._context = context
        self._current_task: TaskMetrics | None = None
        self._aggregate = AgentMetrics()

    def start_task(self, task_id: str) -> None:
        """Start tracking a new task."""
        self._current_task = TaskMetrics(task_id=task_id)
        logger.info("📊 Metrics: Started tracking task %s", task_id)

    def record_iteration(self) -> None:
        """Record a completed iteration."""
        if self._current_task:
            self._current_task.iterations_count += 1

    def record_error(self) -> None:
        """Record an error."""
        if self._current_task:
            self._current_task.error_count += 1

    def record_high_risk_action(self) -> None:
        """Record a high-risk action."""
        if self._current_task:
            self._current_task.high_risk_actions += 1

    def record_stuck_detection(self) -> None:
        """Record a stuck detection event."""
        if self._current_task:
            self._current_task.stuck_detections += 1

    def record_llm_call(self, cost: float = 0.0) -> None:
        """Record an LLM call with optional cost."""
        if self._current_task:
            self._current_task.llm_calls += 1
            self._current_task.total_cost += cost

    def complete_task(
        self, success: bool, failure_reason: str | None = None
    ) -> TaskMetrics:
        """Mark task as complete and update aggregate metrics."""
        if not self._current_task:
            logger.warning("📊 Metrics: No active task to complete")
            return TaskMetrics(task_id="unknown", success=False)

        self._current_task.completed_at = time.time()
        self._current_task.success = success
        self._current_task.failure_reason = failure_reason

        # Update aggregate metrics
        self._aggregate.total_tasks += 1
        if success:
            self._aggregate.successful_tasks += 1
        else:
            self._aggregate.failed_tasks += 1

        self._aggregate.total_iterations += self._current_task.iterations_count
        self._aggregate.total_errors += self._current_task.error_count
        self._aggregate.total_llm_calls += self._current_task.llm_calls
        self._aggregate.total_cost += self._current_task.total_cost
        self._aggregate.total_duration_seconds += self._current_task.duration_seconds

        logger.info(
            "📊 Metrics: Task %s completed - success=%s, duration=%.2fs, iterations=%d, cost=$%.4f",
            self._current_task.task_id,
            success,
            self._current_task.duration_seconds,
            self._current_task.iterations_count,
            self._current_task.total_cost,
        )

        completed_task = self._current_task
        self._current_task = None
        return completed_task

    def get_current_task_metrics(self) -> TaskMetrics | None:
        """Get metrics for the currently running task."""
        return self._current_task

    def get_aggregate_metrics(self) -> AgentMetrics:
        """Get aggregate metrics across all tasks."""
        return self._aggregate

    def reset(self) -> None:
        """Reset all metrics."""
        self._current_task = None
        self._aggregate = AgentMetrics()
        logger.info("📊 Metrics: Reset all metrics")
