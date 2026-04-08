"""Mixin for handling task-tracking actions (update / view).

Extracts task-tracking logic from ``Runtime`` to reduce the size of
``base.py`` and keep concerns separated.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from backend.core.task_status import (
    TASK_STATUS_MARKDOWN_ICONS,
    TASK_STATUS_TODO,
    normalize_task_status,
)
from backend.ledger.observation import (
    ErrorObservation,
    NullObservation,
    Observation,
    TaskTrackingObservation,
)
from backend.persistence.locations import get_conversation_dir

logger = logging.getLogger(__name__)

_TASK_TRACKER_NOOP_PREFIX = '[TASK_TRACKER] Update skipped because the plan is unchanged.'

if TYPE_CHECKING:
    from backend.ledger.action import TaskTrackingAction


class TaskTrackingMixin:
    """Mixin that adds task-tracking capabilities to a Runtime."""

    if TYPE_CHECKING:
        sid: str
        event_stream: Any

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def _handle_task_tracking_action(self, action: TaskTrackingAction) -> Observation:
        """Handle task tracking actions (update/view)."""
        if self.event_stream is None:
            return ErrorObservation('Task tracking requires an event stream')

        conversation_dir = get_conversation_dir(self.sid, self.event_stream.user_id)
        task_file_path = f'{conversation_dir}TASKS.md'

        if action.command == 'update':
            return self._handle_task_update_action(action, task_file_path)
        if action.command == 'view':
            # Always read TASKS.md for view. The engine may hydrate task_list from
            # active_plan.json on the same action; that must not be treated as a task-list write.
            count = getattr(self, '_consecutive_task_view_count', 0) + 1
            self._consecutive_task_view_count = count
            return self._handle_task_view_action(
                action, task_file_path, view_count=count
            )
        return NullObservation('')

    # ------------------------------------------------------------------
    # Update / View handlers
    # ------------------------------------------------------------------

    def _handle_task_update_action(
        self, action: TaskTrackingAction, task_file_path: str
    ) -> Observation:
        """Handle task update command — create / overwrite the task list."""
        thought = (getattr(action, 'thought', '') or '').strip()
        if thought.startswith(_TASK_TRACKER_NOOP_PREFIX):
            self._consecutive_task_view_count = 0
            return TaskTrackingObservation(
                content=thought,
                command=action.command,
                task_list=action.task_list,
            )

        try:
            content = self._generate_task_list_content(action.task_list)
        except ValueError as e:
            return ErrorObservation(f'Invalid task list: {e!s}')
        n = len(action.task_list)

        try:
            assert self.event_stream is not None
            self.event_stream.file_store.write(task_file_path, content)
        except Exception as e:
            return ErrorObservation(
                f'Failed to write task list to session directory {task_file_path}: {e!s}'
            )

        self._consecutive_task_view_count = 0

        msg = f'✅ Plan updated with {n} tasks. Now begin implementing the first todo task.'

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
                content = 'No task list found.'
            except Exception as e:
                content = f'Failed to read task list: {e!s}'
            intervention = (
                '\n\n⚠️ LOOP DETECTED: You have viewed your task list '
                f'{view_count} times without making progress. '
                'STOP calling task_tracker view. '
                'Pick the first todo task and start working on it.'
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
                content=content + '\n\n→ Now implement the first todo (⏳) task.',
                command=action.command,
                task_list=[],
            )
        except FileNotFoundError:
            return TaskTrackingObservation(
                command=action.command,
                task_list=[],
                content='No task list found. Use the "update" command to create one.',
            )
        except Exception as e:
            return TaskTrackingObservation(
                command=action.command,
                task_list=[],
                content=f'Failed to read the task list from session directory {task_file_path}. Error: {e!s}',
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_task_list_content(task_list: list) -> str:
        """Generate markdown content for task list."""
        content = '# Task List\n\n'
        for i, task in enumerate(task_list, 1):
            status = normalize_task_status(task.get('status'), default=TASK_STATUS_TODO)
            status_icon = TASK_STATUS_MARKDOWN_ICONS[status]
            desc = task.get('description') or 'Untitled'
            result = task.get('result') or ''
            line = f'{i}. {status_icon} **{desc}** `[{status}]`\n'
            if result:
                line += f'   - {result}\n'
            content += line
        return content
