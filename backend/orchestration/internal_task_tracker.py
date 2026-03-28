"""Internal task tracker for autonomous progress monitoring.

This module provides a lightweight task tracker that the agent can use internally
to monitor its own progress without cluttering the user interface.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class Task:
    """A single task or subtask."""

    id: str
    description: str
    done: bool = False
    started: bool = False
    parent_id: str | None = None


class InternalTaskTracker:
    """Internal task tracker for autonomous self-monitoring.

    Unlike the user-facing task_tracker tool, this tracks progress internally
    for logging and autonomous decision-making purposes only.
    """

    def __init__(self) -> None:
        """Initialize the internal task tracker."""
        self.tasks: list[Task] = []
        self.current_task_idx = 0
        self._task_counter = 0
        logger.debug("InternalTaskTracker initialized")

    def add_task(self, description: str, parent_id: str | None = None) -> str:
        """Add a new task to track.

        Args:
            description: Description of the task
            parent_id: Optional parent task ID for subtasks

        Returns:
            The ID of the newly created task

        """
        task_id = f"task_{self._task_counter}"
        self._task_counter += 1

        task = Task(
            id=task_id,
            description=description,
            parent_id=parent_id,
        )

        self.tasks.append(task)
        logger.debug("Added task: %s (%s)", task_id, description)
        return task_id

    def start_task(self, task_id: str) -> None:
        """Mark a task as started.

        Args:
            task_id: ID of the task to start

        """
        for task in self.tasks:
            if task.id == task_id:
                task.started = True
                logger.debug("Started task: %s", task_id)
                break

    def complete_task(self, task_id: str) -> None:
        """Mark a task as completed.

        Args:
            task_id: ID of the task to complete

        """
        for task in self.tasks:
            if task.id == task_id:
                task.done = True
                logger.debug("Completed task: %s", task_id)
                break

    def get_current_task(self) -> Task | None:
        """Get the current active task.

        Returns:
            The current task or None if no tasks exist

        """
        if not self.tasks:
            return None

        # Find first non-completed task
        for task in self.tasks:
            if not task.done:
                return task

        return None

    def get_progress(self) -> dict:
        """Get current progress summary.

        Returns:
            Dictionary containing progress information

        """
        if not self.tasks:
            return self._get_empty_progress()

        counts = self._count_task_statuses()
        current_task = self.get_current_task()

        return {
            "total": len(self.tasks),
            "completed": counts["completed"],
            "in_progress": counts["in_progress"],
            "pending": counts["pending"],
            "current": current_task.description if current_task else None,
            "completion_percentage": self._calculate_completion_percentage(
                counts["completed"]
            ),
        }

    def _get_empty_progress(self) -> dict:
        """Get progress dict for empty task list.

        Returns:
            Empty progress dictionary

        """
        return {
            "total": 0,
            "completed": 0,
            "in_progress": 0,
            "pending": 0,
            "current": None,
            "completion_percentage": 0,
        }

    def _count_task_statuses(self) -> dict[str, int]:
        """Count tasks by status.

        Returns:
            Dictionary with counts for each status

        """
        return {
            "completed": sum(1 for t in self.tasks if t.done),
            "in_progress": sum(1 for t in self.tasks if t.started and not t.done),
            "pending": sum(1 for t in self.tasks if not t.started and not t.done),
        }

    def _calculate_completion_percentage(self, completed: int) -> int:
        """Calculate completion percentage.

        Args:
            completed: Number of completed tasks

        Returns:
            Completion percentage (0-100)

        """
        if not self.tasks:
            return 0
        return int((completed / len(self.tasks)) * 100)

    def log_progress(self) -> None:
        """Log current progress for monitoring."""
        progress = self.get_progress()
        logger.info(
            "Task Progress: %d/%d complete (%d%%) | Current: %s",
            progress["completed"],
            progress["total"],
            progress["completion_percentage"],
            progress["current"] or "None",
        )

    def decompose_task(self, description: str, max_subtasks: int = 5) -> list[str]:
        """Decompose a complex task into subtasks.

        This is a simplified version that can be enhanced with LLM-based
        decomposition in the future.

        Args:
            description: Description of the complex task
            max_subtasks: Maximum number of subtasks to create

        Returns:
            List of subtask IDs created

        """
        # For now, just create a single task
        # In future, this could use LLM to intelligently break down tasks
        task_id = self.add_task(description)
        logger.debug(
            "Task decomposition: created task %s for: %s", task_id, description
        )
        return [task_id]

    def reset(self) -> None:
        """Reset the task tracker."""
        self.tasks = []
        self.current_task_idx = 0
        self._task_counter = 0
        logger.debug("InternalTaskTracker reset")
