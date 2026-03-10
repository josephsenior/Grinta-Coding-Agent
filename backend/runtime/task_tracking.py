"""Mixin for handling task-tracking actions (plan / view).

Extracts task-tracking logic from ``Runtime`` to reduce the size of
``base.py`` and keep concerns separated.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from backend.events.observation import (
    ErrorObservation,
    NullObservation,
    Observation,
    TaskTrackingObservation,
)
from backend.storage.locations import get_conversation_dir

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from backend.events.action import TaskTrackingAction


class TaskTrackingMixin:
    """Mixin that adds task-tracking capabilities to a Runtime."""

    if TYPE_CHECKING:
        sid: str
        event_stream: Any

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def _handle_task_tracking_action(self, action: TaskTrackingAction) -> Observation:
        """Handle task tracking actions (plan/view)."""
        if self.event_stream is None:
            return ErrorObservation("Task tracking requires an event stream")

        conversation_dir = get_conversation_dir(self.sid, self.event_stream.user_id)
        task_file_path = f"{conversation_dir}TASKS.md"

        if action.command in ("plan", "update"):
            return self._handle_task_plan_action(action, task_file_path)
        if action.command == "view":
            # If the agent passed a task_list with a view command, treat it as
            # an update — the model frequently calls view while providing tasks,
            # intending to set the plan rather than read it.
            if action.task_list:
                return self._handle_task_plan_action(action, task_file_path)
            # Track consecutive view-only calls; intervene if stuck in a loop.
            count = getattr(self, "_consecutive_task_view_count", 0) + 1
            self._consecutive_task_view_count = count
            return self._handle_task_view_action(action, task_file_path, view_count=count)
        return NullObservation("")

    # ------------------------------------------------------------------
    # Plan / View handlers
    # ------------------------------------------------------------------

    def _handle_task_plan_action(
        self, action: TaskTrackingAction, task_file_path: str
    ) -> Observation:
        """Handle task plan command — create / update task list."""
        content = self._generate_task_list_content(action.task_list)
        n = len(action.task_list)

        try:
            assert self.event_stream is not None
            self.event_stream.file_store.write(task_file_path, content)
        except Exception as e:
            return ErrorObservation(
                f"Failed to write task list to session directory {task_file_path}: {e!s}"
            )

        msg = (
            f"✅ Plan created with {n} tasks. "
            "Now begin implementing: create the first code file immediately."
        )

        return TaskTrackingObservation(
            content=msg,
            command=action.command,
            task_list=action.task_list,
        )

    def _handle_task_view_action(
        self, action: TaskTrackingAction, task_file_path: str, view_count: int = 1
    ) -> Observation:
        """Handle task view command — read and display task list."""
        # After 3+ consecutive views without a plan update, give a strong directive
        # so the agent breaks out of the view loop and starts implementing.
        if view_count >= 3:
            try:
                assert self.event_stream is not None
                content = self.event_stream.file_store.read(task_file_path)
            except FileNotFoundError:
                content = "No task list found."
            except Exception as e:
                content = f"Failed to read task list: {e!s}"
            intervention = (
                "\n\n⚠️ LOOP DETECTED: You have viewed your task list "
                f"{view_count} times without making progress. "
                "STOP calling task_tracker view. "
                "Pick the first pending task, mark it in_progress with command=update, "
                "then immediately create the file using write_file or str_replace_based_edit."
            )
            return TaskTrackingObservation(
                content=content + intervention,
                command=action.command,
                task_list=[],
            )
        try:
            assert self.event_stream is not None
            content = self.event_stream.file_store.read(task_file_path)
            return TaskTrackingObservation(
                content=content + "\n\n→ Now implement the first pending (⏳) task.",
                command=action.command,
                task_list=[],
            )
        except FileNotFoundError:
            return TaskTrackingObservation(
                command=action.command,
                task_list=[],
                content='No task list found. Use the "plan" command to create one.',
            )
        except Exception as e:
            return TaskTrackingObservation(
                command=action.command,
                task_list=[],
                content=f"Failed to read the task list from session directory {task_file_path}. Error: {e!s}",
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_task_list_content(task_list: list) -> str:
        """Generate markdown content for task list."""
        content = "# Task List\n\n"
        for i, task in enumerate(task_list, 1):
            status_icon = {"todo": "⏳", "in_progress": "🔄", "done": "✅"}.get(
                task.get("status", "todo"),
                "⏳",
            )
            content += (
                f"{i}. {status_icon} {task.get('title', '')}\n{task.get('notes', '')}\n"
            )
        return content
