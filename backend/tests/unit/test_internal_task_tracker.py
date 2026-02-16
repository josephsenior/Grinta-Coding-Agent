"""Unit tests for backend.controller.internal_task_tracker — Task tracking."""

from __future__ import annotations

import pytest

from backend.controller.internal_task_tracker import InternalTaskTracker, Task


# ---------------------------------------------------------------------------
# Task dataclass
# ---------------------------------------------------------------------------


class TestTask:
    def test_defaults(self):
        t = Task(id="t1", description="Do something")
        assert t.done is False
        assert t.started is False
        assert t.parent_id is None

    def test_with_parent(self):
        t = Task(id="t2", description="Sub task", parent_id="t1")
        assert t.parent_id == "t1"


# ---------------------------------------------------------------------------
# InternalTaskTracker — initialization
# ---------------------------------------------------------------------------


class TestTrackerInit:
    def test_empty_on_init(self):
        tracker = InternalTaskTracker()
        assert tracker.tasks == []
        assert tracker._task_counter == 0

    def test_reset(self):
        tracker = InternalTaskTracker()
        tracker.add_task("task 1")
        tracker.add_task("task 2")
        assert len(tracker.tasks) == 2

        tracker.reset()
        assert tracker.tasks == []
        assert tracker._task_counter == 0
        assert tracker.current_task_idx == 0


# ---------------------------------------------------------------------------
# add_task
# ---------------------------------------------------------------------------


class TestAddTask:
    def test_adds_task_with_sequential_id(self):
        tracker = InternalTaskTracker()
        id1 = tracker.add_task("First task")
        id2 = tracker.add_task("Second task")
        assert id1 == "task_0"
        assert id2 == "task_1"
        assert len(tracker.tasks) == 2

    def test_task_description_stored(self):
        tracker = InternalTaskTracker()
        tracker.add_task("Implement feature X")
        assert tracker.tasks[0].description == "Implement feature X"

    def test_subtask_with_parent(self):
        tracker = InternalTaskTracker()
        parent = tracker.add_task("Main task")
        child = tracker.add_task("Sub task", parent_id=parent)
        assert tracker.tasks[1].parent_id == parent

    def test_new_tasks_not_started_or_done(self):
        tracker = InternalTaskTracker()
        tracker.add_task("Test")
        assert tracker.tasks[0].started is False
        assert tracker.tasks[0].done is False


# ---------------------------------------------------------------------------
# start_task / complete_task
# ---------------------------------------------------------------------------


class TestTaskLifecycle:
    def test_start_task(self):
        tracker = InternalTaskTracker()
        tid = tracker.add_task("Test")
        tracker.start_task(tid)
        assert tracker.tasks[0].started is True
        assert tracker.tasks[0].done is False

    def test_complete_task(self):
        tracker = InternalTaskTracker()
        tid = tracker.add_task("Test")
        tracker.start_task(tid)
        tracker.complete_task(tid)
        assert tracker.tasks[0].done is True

    def test_complete_without_start(self):
        tracker = InternalTaskTracker()
        tid = tracker.add_task("Test")
        tracker.complete_task(tid)
        assert tracker.tasks[0].done is True

    def test_start_nonexistent_task_noop(self):
        tracker = InternalTaskTracker()
        tracker.add_task("Test")
        tracker.start_task("nonexistent")  # Should not raise
        assert tracker.tasks[0].started is False

    def test_complete_nonexistent_task_noop(self):
        tracker = InternalTaskTracker()
        tracker.add_task("Test")
        tracker.complete_task("nonexistent")  # Should not raise
        assert tracker.tasks[0].done is False


# ---------------------------------------------------------------------------
# get_current_task
# ---------------------------------------------------------------------------


class TestGetCurrentTask:
    def test_returns_none_when_empty(self):
        tracker = InternalTaskTracker()
        assert tracker.get_current_task() is None

    def test_returns_first_incomplete_task(self):
        tracker = InternalTaskTracker()
        t1 = tracker.add_task("First")
        t2 = tracker.add_task("Second")
        current = tracker.get_current_task()
        assert current is not None
        assert current.id == t1

    def test_skips_completed_tasks(self):
        tracker = InternalTaskTracker()
        t1 = tracker.add_task("First")
        t2 = tracker.add_task("Second")
        tracker.complete_task(t1)
        current = tracker.get_current_task()
        assert current is not None
        assert current.id == t2

    def test_all_done_returns_none(self):
        tracker = InternalTaskTracker()
        t1 = tracker.add_task("First")
        t2 = tracker.add_task("Second")
        tracker.complete_task(t1)
        tracker.complete_task(t2)
        assert tracker.get_current_task() is None


# ---------------------------------------------------------------------------
# get_progress
# ---------------------------------------------------------------------------


class TestGetProgress:
    def test_empty_progress(self):
        tracker = InternalTaskTracker()
        p = tracker.get_progress()
        assert p["total"] == 0
        assert p["completed"] == 0
        assert p["in_progress"] == 0
        assert p["pending"] == 0
        assert p["current"] is None

    def test_all_pending(self):
        tracker = InternalTaskTracker()
        tracker.add_task("A")
        tracker.add_task("B")
        tracker.add_task("C")
        p = tracker.get_progress()
        assert p["total"] == 3
        assert p["pending"] == 3
        assert p["completed"] == 0
        assert p["in_progress"] == 0
        assert p["completion_percentage"] == 0

    def test_mixed_status(self):
        tracker = InternalTaskTracker()
        t1 = tracker.add_task("Done")
        t2 = tracker.add_task("In progress")
        t3 = tracker.add_task("Pending")
        tracker.complete_task(t1)
        tracker.start_task(t2)
        p = tracker.get_progress()
        assert p["total"] == 3
        assert p["completed"] == 1
        assert p["in_progress"] == 1
        assert p["pending"] == 1
        assert p["completion_percentage"] == 33  # 1/3

    def test_all_complete(self):
        tracker = InternalTaskTracker()
        t1 = tracker.add_task("A")
        t2 = tracker.add_task("B")
        tracker.complete_task(t1)
        tracker.complete_task(t2)
        p = tracker.get_progress()
        assert p["completed"] == 2
        assert p["completion_percentage"] == 100

    def test_current_task_in_progress(self):
        tracker = InternalTaskTracker()
        t1 = tracker.add_task("Current task")
        tracker.start_task(t1)
        p = tracker.get_progress()
        assert p["current"] == "Current task"


# ---------------------------------------------------------------------------
# completion_percentage edge cases
# ---------------------------------------------------------------------------


class TestCompletionPercentage:
    def test_single_task_done(self):
        tracker = InternalTaskTracker()
        t = tracker.add_task("Only task")
        tracker.complete_task(t)
        p = tracker.get_progress()
        assert p["completion_percentage"] == 100

    def test_five_tasks_two_done(self):
        tracker = InternalTaskTracker()
        ids = [tracker.add_task(f"Task {i}") for i in range(5)]
        tracker.complete_task(ids[0])
        tracker.complete_task(ids[1])
        p = tracker.get_progress()
        assert p["completion_percentage"] == 40  # 2/5


# ---------------------------------------------------------------------------
# decompose_task
# ---------------------------------------------------------------------------


class TestDecomposeTask:
    def test_creates_single_task(self):
        tracker = InternalTaskTracker()
        ids = tracker.decompose_task("Complex task")
        assert len(ids) == 1
        assert tracker.tasks[0].description == "Complex task"

    def test_returns_valid_ids(self):
        tracker = InternalTaskTracker()
        ids = tracker.decompose_task("Another task")
        assert all(isinstance(tid, str) for tid in ids)
        assert all(tid.startswith("task_") for tid in ids)


# ---------------------------------------------------------------------------
# log_progress (smoke test)
# ---------------------------------------------------------------------------


class TestLogProgress:
    def test_log_progress_does_not_raise(self):
        tracker = InternalTaskTracker()
        tracker.add_task("A")
        tracker.log_progress()  # Should not raise

    def test_log_progress_empty_does_not_raise(self):
        tracker = InternalTaskTracker()
        tracker.log_progress()  # Should not raise
