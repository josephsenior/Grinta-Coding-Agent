"""Tests for backend.orchestration.internal_task_tracker — Task + InternalTaskTracker."""

from __future__ import annotations

from backend.orchestration.internal_task_tracker import InternalTaskTracker, Task


# ---------------------------------------------------------------------------
# Task dataclass
# ---------------------------------------------------------------------------
class TestTask:
    def test_defaults(self):
        t = Task(id='task_0', description='Do something')
        assert t.done is False
        assert t.started is False
        assert t.parent_id is None

    def test_with_parent(self):
        t = Task(id='task_1', description='Sub', parent_id='task_0')
        assert t.parent_id == 'task_0'


# ---------------------------------------------------------------------------
# InternalTaskTracker init & reset
# ---------------------------------------------------------------------------
class TestTrackerInit:
    def test_init(self):
        tracker = InternalTaskTracker()
        assert tracker.tasks == []
        assert tracker.current_task_idx == 0
        assert tracker._task_counter == 0

    def test_reset(self):
        tracker = InternalTaskTracker()
        tracker.add_task('a')
        tracker.add_task('b')
        tracker.reset()
        assert tracker.tasks == []
        assert tracker._task_counter == 0


# ---------------------------------------------------------------------------
# add_task
# ---------------------------------------------------------------------------
class TestAddTask:
    def test_returns_task_id(self):
        tracker = InternalTaskTracker()
        tid = tracker.add_task('Write tests')
        assert tid == 'task_0'

    def test_increments_counter(self):
        tracker = InternalTaskTracker()
        tracker.add_task('a')
        tracker.add_task('b')
        assert tracker._task_counter == 2

    def test_with_parent(self):
        tracker = InternalTaskTracker()
        p = tracker.add_task('parent')
        tracker.add_task('child', parent_id=p)
        assert tracker.tasks[1].parent_id == p


# ---------------------------------------------------------------------------
# start_task / complete_task
# ---------------------------------------------------------------------------
class TestStartComplete:
    def test_start_task(self):
        tracker = InternalTaskTracker()
        tid = tracker.add_task('foo')
        tracker.start_task(tid)
        assert tracker.tasks[0].started is True

    def test_complete_task(self):
        tracker = InternalTaskTracker()
        tid = tracker.add_task('foo')
        tracker.complete_task(tid)
        assert tracker.tasks[0].done is True

    def test_start_unknown_task_noop(self):
        tracker = InternalTaskTracker()
        tracker.start_task('nonexistent')  # Should not raise

    def test_complete_unknown_task_noop(self):
        tracker = InternalTaskTracker()
        tracker.complete_task('nonexistent')  # Should not raise


# ---------------------------------------------------------------------------
# get_current_task
# ---------------------------------------------------------------------------
class TestGetCurrentTask:
    def test_empty_returns_none(self):
        tracker = InternalTaskTracker()
        assert tracker.get_current_task() is None

    def test_returns_first_incomplete(self):
        tracker = InternalTaskTracker()
        t0 = tracker.add_task('first')
        tracker.add_task('second')
        tracker.complete_task(t0)
        current = tracker.get_current_task()
        assert current is not None
        assert current.description == 'second'

    def test_all_complete_returns_none(self):
        tracker = InternalTaskTracker()
        t0 = tracker.add_task('only')
        tracker.complete_task(t0)
        assert tracker.get_current_task() is None


# ---------------------------------------------------------------------------
# get_progress
# ---------------------------------------------------------------------------
class TestGetProgress:
    def test_empty_progress(self):
        tracker = InternalTaskTracker()
        p = tracker.get_progress()
        assert p['total'] == 0
        assert p['completed'] == 0
        assert p['in_progress'] == 0
        assert p['pending'] == 0
        assert p['current'] is None
        assert p['completion_percentage'] == 0

    def test_mixed_progress(self):
        tracker = InternalTaskTracker()
        t0 = tracker.add_task('a')
        t1 = tracker.add_task('b')
        tracker.add_task('c')
        tracker.complete_task(t0)
        tracker.start_task(t1)
        p = tracker.get_progress()
        assert p['total'] == 3
        assert p['completed'] == 1
        assert p['in_progress'] == 1
        assert p['pending'] == 1
        assert p['current'] == 'b'
        assert p['completion_percentage'] == 33

    def test_all_complete(self):
        tracker = InternalTaskTracker()
        t0 = tracker.add_task('x')
        tracker.complete_task(t0)
        p = tracker.get_progress()
        assert p['completion_percentage'] == 100
        assert p['current'] is None


# ---------------------------------------------------------------------------
# _count_task_statuses
# ---------------------------------------------------------------------------
class TestCountStatuses:
    def test_counts(self):
        tracker = InternalTaskTracker()
        t0 = tracker.add_task('a')
        t1 = tracker.add_task('b')
        tracker.add_task('c')
        tracker.complete_task(t0)
        tracker.start_task(t1)
        counts = tracker._count_task_statuses()
        assert counts['completed'] == 1
        assert counts['in_progress'] == 1
        assert counts['pending'] == 1


# ---------------------------------------------------------------------------
# _calculate_completion_percentage
# ---------------------------------------------------------------------------
class TestCalcPercentage:
    def test_empty(self):
        tracker = InternalTaskTracker()
        assert tracker._calculate_completion_percentage(0) == 0

    def test_half(self):
        tracker = InternalTaskTracker()
        tracker.add_task('a')
        tracker.add_task('b')
        assert tracker._calculate_completion_percentage(1) == 50


# ---------------------------------------------------------------------------
# decompose_task
# ---------------------------------------------------------------------------
class TestDecomposeTask:
    def test_creates_single_task(self):
        tracker = InternalTaskTracker()
        ids = tracker.decompose_task('Complex thing')
        assert len(ids) == 1
        assert tracker.tasks[0].description == 'Complex thing'


# ---------------------------------------------------------------------------
# log_progress
# ---------------------------------------------------------------------------
class TestLogProgress:
    def test_log_does_not_raise(self):
        tracker = InternalTaskTracker()
        tracker.add_task('x')
        tracker.log_progress()  # Just ensure no exception
