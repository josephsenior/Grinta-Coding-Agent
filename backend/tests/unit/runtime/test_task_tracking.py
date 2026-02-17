"""Unit tests for backend.runtime.task_tracking."""

from __future__ import annotations

from unittest import TestCase
from unittest.mock import MagicMock, PropertyMock

from backend.events.action import TaskTrackingAction
from backend.events.observation import (
    ErrorObservation,
    NullObservation,
    TaskTrackingObservation,
)
from backend.runtime.task_tracking import TaskTrackingMixin


class TestTaskTrackingMixin(TestCase):
    """Test TaskTrackingMixin class."""

    def setUp(self):
        """Set up test fixtures."""
        self.mixin = TaskTrackingMixin()
        self.mixin.sid = "test-sid-123"
        self.mixin.event_stream = MagicMock()
        self.mixin.event_stream.user_id = "user-123"

    def test_handle_task_tracking_no_event_stream(self):
        """Test handling task tracking action without event stream."""
        self.mixin.event_stream = None
        action = TaskTrackingAction(command="plan", task_list=[])

        result = self.mixin._handle_task_tracking_action(action)

        self.assertIsInstance(result, ErrorObservation)
        self.assertIn("requires an event stream", result.content)

    def test_handle_task_tracking_plan_command(self):
        """Test handling task plan command."""
        task_list = [
            {"title": "Task 1", "status": "todo", "notes": "Do something"},
            {"title": "Task 2", "status": "in_progress", "notes": "Working on it"},
        ]
        action = TaskTrackingAction(command="plan", task_list=task_list)

        with self.assertPathHandling():
            result = self.mixin._handle_task_tracking_action(action)

        self.assertIsInstance(result, TaskTrackingObservation)
        self.assertEqual(result.command, "plan")
        self.assertEqual(result.task_list, task_list)
        self.assertIn("2 items", result.content)
        self.mixin.event_stream.file_store.write.assert_called_once()

    def test_handle_task_tracking_view_command(self):
        """Test handling task view command."""
        action = TaskTrackingAction(command="view", task_list=[])
        stored_content = "# Task List\n\n1. ⏳ Task 1\nNotes here\n"
        self.mixin.event_stream.file_store.read.return_value = stored_content

        with self.assertPathHandling():
            result = self.mixin._handle_task_tracking_action(action)

        self.assertIsInstance(result, TaskTrackingObservation)
        self.assertEqual(result.command, "view")
        self.assertEqual(result.content, stored_content)
        self.mixin.event_stream.file_store.read.assert_called_once()

    def test_handle_task_tracking_unknown_command(self):
        """Test handling unknown command returns NullObservation."""
        action = TaskTrackingAction(command="unknown", task_list=[])

        result = self.mixin._handle_task_tracking_action(action)

        self.assertIsInstance(result, NullObservation)

    def test_handle_task_plan_action_successful(self):
        """Test successful task plan action."""
        task_list = [
            {"title": "Task 1", "status": "todo", "notes": "Note 1"},
        ]
        action = TaskTrackingAction(command="plan", task_list=task_list)
        task_file_path = "/path/to/TASKS.md"

        result = self.mixin._handle_task_plan_action(action, task_file_path)

        self.assertIsInstance(result, TaskTrackingObservation)
        self.assertEqual(result.command, "plan")
        self.assertEqual(result.task_list, task_list)
        self.assertIn("1 items", result.content)
        self.assertIn(task_file_path, result.content)
        self.mixin.event_stream.file_store.write.assert_called_once()

    def test_handle_task_plan_action_write_failure(self):
        """Test task plan action when file write fails."""
        task_list = [{"title": "Task 1", "status": "todo"}]
        action = TaskTrackingAction(command="plan", task_list=task_list)
        task_file_path = "/path/to/TASKS.md"
        self.mixin.event_stream.file_store.write.side_effect = IOError("Write failed")

        result = self.mixin._handle_task_plan_action(action, task_file_path)

        self.assertIsInstance(result, ErrorObservation)
        self.assertIn("Failed to write", result.content)
        self.assertIn(task_file_path, result.content)

    def test_handle_task_plan_action_empty_task_list(self):
        """Test task plan action with empty task list."""
        action = TaskTrackingAction(command="plan", task_list=[])
        task_file_path = "/path/to/TASKS.md"

        result = self.mixin._handle_task_plan_action(action, task_file_path)

        self.assertIsInstance(result, TaskTrackingObservation)
        self.assertIn("0 items", result.content)

    def test_handle_task_view_action_successful(self):
        """Test successful task view action."""
        action = TaskTrackingAction(command="view", task_list=[])
        task_file_path = "/path/to/TASKS.md"
        stored_content = "# Task List\n\n1. ⏳ My Task\nNotes\n"
        self.mixin.event_stream.file_store.read.return_value = stored_content

        result = self.mixin._handle_task_view_action(action, task_file_path)

        self.assertIsInstance(result, TaskTrackingObservation)
        self.assertEqual(result.command, "view")
        self.assertEqual(result.content, stored_content)
        self.assertEqual(result.task_list, [])

    def test_handle_task_view_action_file_not_found(self):
        """Test task view action when file doesn't exist."""
        action = TaskTrackingAction(command="view", task_list=[])
        task_file_path = "/path/to/TASKS.md"
        self.mixin.event_stream.file_store.read.side_effect = FileNotFoundError()

        result = self.mixin._handle_task_view_action(action, task_file_path)

        self.assertIsInstance(result, TaskTrackingObservation)
        self.assertEqual(result.command, "view")
        self.assertIn("No task list found", result.content)
        self.assertEqual(result.task_list, [])

    def test_handle_task_view_action_read_error(self):
        """Test task view action when file read fails."""
        action = TaskTrackingAction(command="view", task_list=[])
        task_file_path = "/path/to/TASKS.md"
        self.mixin.event_stream.file_store.read.side_effect = PermissionError(
            "Access denied"
        )

        result = self.mixin._handle_task_view_action(action, task_file_path)

        self.assertIsInstance(result, TaskTrackingObservation)
        self.assertEqual(result.command, "view")
        self.assertIn("Failed to read", result.content)
        self.assertIn(task_file_path, result.content)

    def test_generate_task_list_content_all_statuses(self):
        """Test task list content generation with all status types."""
        task_list = [
            {"title": "Task 1", "status": "todo", "notes": "Note 1"},
            {"title": "Task 2", "status": "in_progress", "notes": "Note 2"},
            {"title": "Task 3", "status": "done", "notes": "Note 3"},
        ]

        content = TaskTrackingMixin._generate_task_list_content(task_list)

        self.assertIn("# Task List", content)
        self.assertIn("1. ⏳ Task 1", content)
        self.assertIn("2. 🔄 Task 2", content)
        self.assertIn("3. ✅ Task 3", content)
        self.assertIn("Note 1", content)
        self.assertIn("Note 2", content)
        self.assertIn("Note 3", content)

    def test_generate_task_list_content_default_status(self):
        """Test task list content generation with missing/unknown status."""
        task_list = [
            {"title": "Task 1"},
            {"title": "Task 2", "status": "unknown"},
        ]

        content = TaskTrackingMixin._generate_task_list_content(task_list)

        # Both should get default todo icon
        self.assertIn("1. ⏳ Task 1", content)
        self.assertIn("2. ⏳ Task 2", content)

    def test_generate_task_list_content_missing_fields(self):
        """Test task list content generation with missing title/notes."""
        task_list = [
            {"status": "todo"},  # No title
            {"title": "Task 2", "status": "done"},  # No notes
        ]

        content = TaskTrackingMixin._generate_task_list_content(task_list)

        self.assertIn("1. ⏳ ", content)  # Empty title
        self.assertIn("2. ✅ Task 2", content)
        # Should not crash, just use empty strings

    def test_generate_task_list_content_empty_list(self):
        """Test task list content generation with empty list."""
        content = TaskTrackingMixin._generate_task_list_content([])

        self.assertEqual(content, "# Task List\n\n")

    def test_generate_task_list_content_numbering(self):
        """Test task list content has correct numbering."""
        task_list = [
            {"title": f"Task {i}", "status": "todo", "notes": ""} for i in range(1, 6)
        ]

        content = TaskTrackingMixin._generate_task_list_content(task_list)

        for i in range(1, 6):
            self.assertIn(f"{i}. ⏳ Task {i}", content)

    def assertPathHandling(self):
        """Context manager for tests that use conversation_dir."""
        import unittest.mock as mock

        return mock.patch(
            "backend.runtime.task_tracking.get_conversation_dir",
            return_value="/test/conversation/dir/",
        )

    def test_task_file_path_construction(self):
        """Test that task file path is correctly constructed."""
        action = TaskTrackingAction(command="plan", task_list=[])

        with self.assertPathHandling() as mock_get_dir:
            self.mixin._handle_task_tracking_action(action)
            mock_get_dir.assert_called_once_with(
                self.mixin.sid, self.mixin.event_stream.user_id
            )

    def test_multiple_task_operations(self):
        """Test sequence of plan and view operations."""
        # First plan some tasks
        task_list = [{"title": "Task 1", "status": "todo", "notes": ""}]
        plan_action = TaskTrackingAction(command="plan", task_list=task_list)

        with self.assertPathHandling():
            plan_result = self.mixin._handle_task_tracking_action(plan_action)

        self.assertIsInstance(plan_result, TaskTrackingObservation)

        # Then view them
        view_action = TaskTrackingAction(command="view", task_list=[])
        self.mixin.event_stream.file_store.read.return_value = "# Task List\n\n1. ⏳ Task 1\n"

        with self.assertPathHandling():
            view_result = self.mixin._handle_task_tracking_action(view_action)

        self.assertIsInstance(view_result, TaskTrackingObservation)
        self.assertIn("Task 1", view_result.content)

    def test_task_list_with_special_characters(self):
        """Test task list content with special characters."""
        task_list = [
            {
                "title": "Task with 'quotes' and \"double quotes\"",
                "status": "todo",
                "notes": "Notes with <html> & special chars",
            }
        ]

        content = TaskTrackingMixin._generate_task_list_content(task_list)

        self.assertIn("'quotes'", content)
        self.assertIn('"double quotes"', content)
        self.assertIn("<html>", content)
        self.assertIn("&", content)

    def test_task_list_with_newlines_in_notes(self):
        """Test task list content with newlines in notes."""
        task_list = [
            {
                "title": "Task 1",
                "status": "todo",
                "notes": "Line 1\nLine 2\nLine 3",
            }
        ]

        content = TaskTrackingMixin._generate_task_list_content(task_list)

        self.assertIn("Line 1", content)
        self.assertIn("Line 2", content)
        self.assertIn("Line 3", content)
