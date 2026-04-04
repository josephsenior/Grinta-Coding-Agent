"""Unit tests for backend.orchestration.internal_task_tracker module.

Tests cover:
- Task dataclass creation
- InternalTaskTracker initialization
- add_task with and without parent_id
- start_task, complete_task methods
- get_current_task finding logic
- get_progress summary with various states
- _count_task_statuses helper
- log_progress method
- decompose_task functionality
- reset method
"""

from backend.orchestration.internal_task_tracker import InternalTaskTracker, Task


class TestTask:
    """Test Task dataclass."""

    def test_task_creation(self):
        """Task should be created with required fields."""
        task = Task(id='task_1', description='Test task')

        assert task.id == 'task_1'
        assert task.description == 'Test task'
        assert task.done is False
        assert task.started is False
        assert task.parent_id is None

    def test_task_with_all_fields(self):
        """Task should accept all optional fields."""
        task = Task(
            id='task_2',
            description='Subtask',
            done=True,
            started=True,
            parent_id='task_1',
        )

        assert task.id == 'task_2'
        assert task.done is True
        assert task.started is True
        assert task.parent_id == 'task_1'


class TestInternalTaskTrackerInit:
    """Test InternalTaskTracker initialization."""

    def test_init_creates_empty_tracker(self):
        """Should initialize with empty task list."""
        tracker = InternalTaskTracker()

        assert tracker.tasks == []
        assert tracker.current_task_idx == 0
        assert tracker._task_counter == 0


class TestAddTask:
    """Test add_task method."""

    def test_add_task_creates_task_with_id(self):
        """add_task should create a task with auto-generated ID."""
        tracker = InternalTaskTracker()

        task_id = tracker.add_task('First task')

        assert task_id == 'task_0'
        assert len(tracker.tasks) == 1
        assert tracker.tasks[0].id == 'task_0'
        assert tracker.tasks[0].description == 'First task'

    def test_add_task_increments_counter(self):
        """add_task should increment task counter for unique IDs."""
        tracker = InternalTaskTracker()

        task_id_1 = tracker.add_task('Task 1')
        task_id_2 = tracker.add_task('Task 2')

        assert task_id_1 == 'task_0'
        assert task_id_2 == 'task_1'
        assert tracker._task_counter == 2

    def test_add_task_with_parent_id(self):
        """add_task should support parent_id for subtasks."""
        tracker = InternalTaskTracker()

        parent_id = tracker.add_task('Parent task')
        child_id = tracker.add_task('Child task', parent_id=parent_id)

        child = tracker.tasks[1]
        assert child.id == child_id
        assert child.parent_id == parent_id

    def test_add_task_defaults_to_not_started_not_done(self):
        """New tasks should default to not started and not done."""
        tracker = InternalTaskTracker()

        tracker.add_task('Task')

        task = tracker.tasks[0]
        assert task.started is False
        assert task.done is False


class TestStartTask:
    """Test start_task method."""

    def test_start_task_marks_task_as_started(self):
        """start_task should set started flag to True."""
        tracker = InternalTaskTracker()
        task_id = tracker.add_task('Task to start')

        tracker.start_task(task_id)

        task = tracker.tasks[0]
        assert task.started is True

    def test_start_task_with_invalid_id_does_nothing(self):
        """start_task should handle invalid task ID gracefully."""
        tracker = InternalTaskTracker()
        tracker.add_task('Task')

        # Should not raise
        tracker.start_task('invalid_id')

        # Task should remain not started
        assert tracker.tasks[0].started is False


class TestCompleteTask:
    """Test complete_task method."""

    def test_complete_task_marks_task_as_done(self):
        """complete_task should set done flag to True."""
        tracker = InternalTaskTracker()
        task_id = tracker.add_task('Task to complete')

        tracker.complete_task(task_id)

        task = tracker.tasks[0]
        assert task.done is True

    def test_complete_task_with_invalid_id_does_nothing(self):
        """complete_task should handle invalid task ID gracefully."""
        tracker = InternalTaskTracker()
        tracker.add_task('Task')

        # Should not raise
        tracker.complete_task('invalid_id')

        # Task should remain not done
        assert tracker.tasks[0].done is False


class TestGetCurrentTask:
    """Test get_current_task method."""

    def test_get_current_task_with_no_tasks(self):
        """get_current_task should return None with empty list."""
        tracker = InternalTaskTracker()

        current = tracker.get_current_task()

        assert current is None

    def test_get_current_task_returns_first_uncompleted(self):
        """get_current_task should return first non-completed task."""
        tracker = InternalTaskTracker()
        tracker.add_task('Task 1')
        task_2_id = tracker.add_task('Task 2')
        tracker.add_task('Task 3')

        # Complete first task
        tracker.tasks[0].done = True

        current = tracker.get_current_task()

        assert current is not None
        assert current.id == task_2_id

    def test_get_current_task_all_completed_returns_none(self):
        """get_current_task should return None when all tasks are done."""
        tracker = InternalTaskTracker()
        tracker.add_task('Task 1')
        tracker.add_task('Task 2')

        # Complete all
        for task in tracker.tasks:
            task.done = True

        current = tracker.get_current_task()

        assert current is None


class TestGetProgress:
    """Test get_progress method."""

    def test_get_progress_with_no_tasks(self):
        """get_progress should return empty progress with no tasks."""
        tracker = InternalTaskTracker()

        progress = tracker.get_progress()

        assert progress['total'] == 0
        assert progress['completed'] == 0
        assert progress['in_progress'] == 0
        assert progress['pending'] == 0
        assert progress['current'] is None
        assert progress['completion_percentage'] == 0

    def test_get_progress_with_all_pending(self):
        """get_progress should show all tasks as pending."""
        tracker = InternalTaskTracker()
        tracker.add_task('Task 1')
        tracker.add_task('Task 2')
        tracker.add_task('Task 3')

        progress = tracker.get_progress()

        assert progress['total'] == 3
        assert progress['completed'] == 0
        assert progress['in_progress'] == 0
        assert progress['pending'] == 3
        assert progress['completion_percentage'] == 0

    def test_get_progress_with_mixed_states(self):
        """get_progress should correctly count all task states."""
        tracker = InternalTaskTracker()

        # Completed
        task1_id = tracker.add_task('Task 1')
        tracker.start_task(task1_id)
        tracker.complete_task(task1_id)

        # In progress
        task2_id = tracker.add_task('Task 2')
        tracker.start_task(task2_id)

        # Pending
        tracker.add_task('Task 3')

        progress = tracker.get_progress()

        assert progress['total'] == 3
        assert progress['completed'] == 1
        assert progress['in_progress'] == 1
        assert progress['pending'] == 1
        assert progress['completion_percentage'] == 33  # 1/3 = 33%

    def test_get_progress_includes_current_task(self):
        """get_progress should include current task description."""
        tracker = InternalTaskTracker()
        tracker.add_task('First task')
        tracker.add_task('Second task')

        progress = tracker.get_progress()

        assert progress['current'] == 'First task'

    def test_get_progress_completion_percentage(self):
        """get_progress should calculate correct completion percentage."""
        tracker = InternalTaskTracker()

        # Add 4 tasks, complete 2
        for i in range(4):
            task_id = tracker.add_task(f'Task {i}')
            if i < 2:
                tracker.complete_task(task_id)

        progress = tracker.get_progress()

        assert progress['completion_percentage'] == 50  # 2/4 = 50%


class TestCountTaskStatuses:
    """Test _count_task_statuses helper method."""

    def test_count_task_statuses_empty(self):
        """_count_task_statuses should return zero counts for empty list."""
        tracker = InternalTaskTracker()

        counts = tracker._count_task_statuses()

        assert counts['completed'] == 0
        assert counts['in_progress'] == 0
        assert counts['pending'] == 0

    def test_count_task_statuses_all_types(self):
        """_count_task_statuses should count all task types correctly."""
        tracker = InternalTaskTracker()

        # Completed
        task1_id = tracker.add_task('Task 1')
        tracker.start_task(task1_id)
        tracker.complete_task(task1_id)

        # In progress
        task2_id = tracker.add_task('Task 2')
        tracker.start_task(task2_id)

        # Pending
        tracker.add_task('Task 3')

        counts = tracker._count_task_statuses()

        assert counts['completed'] == 1
        assert counts['in_progress'] == 1
        assert counts['pending'] == 1


class TestCalculateCompletionPercentage:
    """Test _calculate_completion_percentage helper method."""

    def test_calculate_completion_percentage_empty(self):
        """Should return 0 for empty task list."""
        tracker = InternalTaskTracker()

        percentage = tracker._calculate_completion_percentage(0)

        assert percentage == 0

    def test_calculate_completion_percentage_half(self):
        """Should return 50 for half completed."""
        tracker = InternalTaskTracker()
        tracker.add_task('Task 1')
        tracker.add_task('Task 2')

        percentage = tracker._calculate_completion_percentage(1)

        assert percentage == 50

    def test_calculate_completion_percentage_all(self):
        """Should return 100 for all completed."""
        tracker = InternalTaskTracker()
        tracker.add_task('Task 1')
        tracker.add_task('Task 2')

        percentage = tracker._calculate_completion_percentage(2)

        assert percentage == 100


class TestLogProgress:
    """Test log_progress method."""

    def test_log_progress_does_not_raise(self):
        """log_progress should not raise exceptions."""
        tracker = InternalTaskTracker()
        tracker.add_task('Task 1')

        # Should not raise
        tracker.log_progress()

    def test_log_progress_with_empty_tracker(self):
        """log_progress should handle empty tracker."""
        tracker = InternalTaskTracker()

        # Should not raise
        tracker.log_progress()


class TestDecomposeTask:
    """Test decompose_task method."""

    def test_decompose_task_creates_single_task(self):
        """decompose_task should create a task for the description."""
        tracker = InternalTaskTracker()

        subtask_ids = tracker.decompose_task('Complex task')

        assert len(subtask_ids) == 1
        assert len(tracker.tasks) == 1
        assert tracker.tasks[0].description == 'Complex task'

    def test_decompose_task_returns_task_ids(self):
        """decompose_task should return list of created task IDs."""
        tracker = InternalTaskTracker()

        subtask_ids = tracker.decompose_task('Another task')

        assert len(subtask_ids) == 1
        assert subtask_ids[0] == 'task_0'

    def test_decompose_task_accepts_max_subtasks_param(self):
        """decompose_task should accept max_subtasks parameter."""
        tracker = InternalTaskTracker()

        # Should not raise (parameter currently unused but accepted)
        subtask_ids = tracker.decompose_task('Task', max_subtasks=10)

        assert subtask_ids


class TestReset:
    """Test reset method."""

    def test_reset_clears_all_tasks(self):
        """Reset should clear all tasks."""
        tracker = InternalTaskTracker()
        tracker.add_task('Task 1')
        tracker.add_task('Task 2')

        tracker.reset()

        assert tracker.tasks == []
        assert tracker.current_task_idx == 0
        assert tracker._task_counter == 0

    def test_reset_after_progress(self):
        """Reset should restore tracker to initial state."""
        tracker = InternalTaskTracker()

        # Add and complete some tasks
        task_id = tracker.add_task('Task 1')
        tracker.start_task(task_id)
        tracker.complete_task(task_id)

        tracker.reset()

        # Should be like new
        assert not tracker.tasks
        progress = tracker.get_progress()
        assert progress['total'] == 0


class TestGetEmptyProgress:
    """Test _get_empty_progress helper method."""

    def test_get_empty_progress_structure(self):
        """_get_empty_progress should return proper empty structure."""
        tracker = InternalTaskTracker()

        empty_progress = tracker._get_empty_progress()

        assert empty_progress['total'] == 0
        assert empty_progress['completed'] == 0
        assert empty_progress['in_progress'] == 0
        assert empty_progress['pending'] == 0
        assert empty_progress['current'] is None
        assert empty_progress['completion_percentage'] == 0
