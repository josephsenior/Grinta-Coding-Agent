"""Tests for backend.controller.progress_tracker — ProgressTracker & ProgressMetrics."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from backend.controller.progress_tracker import (
    Milestone,
    ProgressMetrics,
    ProgressTracker,
)


# ---------------------------------------------------------------------------
# Data class defaults
# ---------------------------------------------------------------------------
class TestMilestone:
    def test_creation(self):
        m = Milestone(name="tests_passing", iteration=5, timestamp=datetime.now())
        assert m.name == "tests_passing"
        assert m.iteration == 5
        assert m.description == ""

    def test_with_description(self):
        m = Milestone(
            name="commit", iteration=10, timestamp=datetime.now(), description="First commit"
        )
        assert m.description == "First commit"


class TestProgressMetrics:
    def test_defaults(self):
        pm = ProgressMetrics()
        assert pm.completion_percentage == 0.0
        assert pm.iterations_completed == 0
        assert pm.velocity == 0.0
        assert pm.estimated_completion_time is None
        assert pm.milestones_reached == []
        assert pm.is_making_progress is True
        assert pm.stagnation_iterations == 0


# ---------------------------------------------------------------------------
# ProgressTracker init
# ---------------------------------------------------------------------------
class TestProgressTrackerInit:
    def test_init(self):
        tracker = ProgressTracker(max_iterations=100)
        assert tracker.max_iterations == 100
        assert tracker.last_progress_iteration == 0
        assert tracker.files_modified == set()
        assert tracker.tests_run == 0
        assert tracker.tests_passed == 0
        assert tracker.error_count == 0
        assert tracker.consecutive_errors == 0


# ---------------------------------------------------------------------------
# _calculate_velocity
# ---------------------------------------------------------------------------
class TestCalculateVelocity:
    def test_zero_elapsed(self):
        tracker = ProgressTracker(max_iterations=100)
        # Immediately after init, elapsed is ~0
        v = tracker._calculate_velocity(0)
        assert v == 0.0

    def test_positive_velocity(self):
        tracker = ProgressTracker(max_iterations=100)
        # Fake start_time to 60 seconds ago
        from datetime import timedelta

        tracker.start_time = datetime.now() - timedelta(minutes=2)
        v = tracker._calculate_velocity(10)
        assert v == pytest.approx(5.0, rel=0.2)  # ~5 iterations per minute


# ---------------------------------------------------------------------------
# _is_making_progress
# ---------------------------------------------------------------------------
class TestIsMakingProgress:
    def test_recent_progress(self):
        tracker = ProgressTracker(max_iterations=100)
        tracker.last_progress_iteration = 8
        assert tracker._is_making_progress(10) is True  # 2 < window(10)

    def test_stagnated(self):
        tracker = ProgressTracker(max_iterations=100)
        tracker.last_progress_iteration = 0
        assert tracker._is_making_progress(15) is False  # 15 >= window(10)

    def test_custom_window(self):
        tracker = ProgressTracker(max_iterations=100)
        tracker.last_progress_iteration = 5
        assert tracker._is_making_progress(10, window=4) is False  # 5 >= 4


# ---------------------------------------------------------------------------
# _estimate_completion_time
# ---------------------------------------------------------------------------
class TestEstimateCompletionTime:
    def test_zero_velocity_returns_none(self):
        tracker = ProgressTracker(max_iterations=100)
        assert tracker._estimate_completion_time(0.5, 0.0) is None

    def test_already_complete(self):
        tracker = ProgressTracker(max_iterations=100)
        assert tracker._estimate_completion_time(1.0, 5.0) is None

    def test_returns_future_datetime(self):
        tracker = ProgressTracker(max_iterations=100)
        eta = tracker._estimate_completion_time(0.5, 10.0)
        assert eta is not None
        assert eta > datetime.now()

    def test_very_slow_returns_none(self):
        tracker = ProgressTracker(max_iterations=1_000_000)
        result = tracker._estimate_completion_time(0.0, 0.0001)
        # With insane remaining_iterations, minutes_remaining > 10000
        assert result is None


# ---------------------------------------------------------------------------
# _calculate_completion_percentage
# ---------------------------------------------------------------------------
class TestCalculateCompletionPercentage:
    def _make_state(self, iteration=0, history=None):
        state = MagicMock()
        state.iteration_flag.current_value = iteration
        state.history = history or []
        return state

    def test_zero_state(self):
        tracker = ProgressTracker(max_iterations=100)
        state = self._make_state(iteration=0)
        pct = tracker._calculate_completion_percentage(state)
        assert pct == 0.0

    def test_partial_progress(self):
        tracker = ProgressTracker(max_iterations=100)
        tracker.files_modified = {"a.py", "b.py", "c.py", "d.py", "e.py"}
        tracker.tests_run = 10
        tracker.tests_passed = 10
        tracker.milestones = [
            Milestone(name="m1", iteration=1, timestamp=datetime.now())
        ]
        state = self._make_state(iteration=50)
        pct = tracker._calculate_completion_percentage(state)
        assert 0.0 < pct <= 1.0

    def test_capped_at_one(self):
        tracker = ProgressTracker(max_iterations=10)
        tracker.files_modified = {f"f{i}.py" for i in range(20)}
        tracker.tests_run = 100
        tracker.tests_passed = 100
        tracker.milestones = [
            Milestone(name=f"m{i}", iteration=i, timestamp=datetime.now())
            for i in range(20)
        ]
        state = self._make_state(iteration=10)
        pct = tracker._calculate_completion_percentage(state)
        assert pct <= 1.0


# ---------------------------------------------------------------------------
# _track_file_modifications
# ---------------------------------------------------------------------------
class TestTrackFileModifications:
    def test_tracks_file_edit_actions(self):
        from backend.events.action import FileEditAction

        tracker = ProgressTracker(max_iterations=100)
        action = FileEditAction(path="/tmp/x.py", content="pass")
        state = MagicMock()
        state.history = [action]
        tracker._track_file_modifications(state)
        assert "/tmp/x.py" in tracker.files_modified

    def test_ignores_non_edit_events(self):
        tracker = ProgressTracker(max_iterations=100)
        state = MagicMock()
        state.history = [MagicMock(spec=[])]
        tracker._track_file_modifications(state)
        assert tracker.files_modified == set()


# ---------------------------------------------------------------------------
# _track_test_executions
# ---------------------------------------------------------------------------
class TestTrackTestExecutions:
    def test_tracks_pytest_pass(self):
        from backend.events.action import CmdRunAction
        from backend.events.observation import CmdOutputObservation

        tracker = ProgressTracker(max_iterations=100)
        cmd = CmdRunAction(command="pytest tests/")
        obs = CmdOutputObservation(content="passed", command="pytest", exit_code=0)
        state = MagicMock()
        state.history = [cmd, obs]
        tracker._track_test_executions(state)
        assert tracker.tests_run == 1
        assert tracker.tests_passed == 1

    def test_tracks_pytest_fail(self):
        from backend.events.action import CmdRunAction
        from backend.events.observation import CmdOutputObservation

        tracker = ProgressTracker(max_iterations=100)
        cmd = CmdRunAction(command="pytest tests/")
        obs = CmdOutputObservation(content="failed", command="pytest", exit_code=1)
        state = MagicMock()
        state.history = [cmd, obs]
        tracker._track_test_executions(state)
        assert tracker.tests_run == 1
        assert tracker.tests_passed == 0


# ---------------------------------------------------------------------------
# _detect_milestones
# ---------------------------------------------------------------------------
class TestDetectMilestones:
    def test_detects_pytest_passing(self):
        from backend.events.observation import CmdOutputObservation

        tracker = ProgressTracker(max_iterations=100)
        obs = CmdOutputObservation(content="passed", command="pytest tests/", exit_code=0)
        state = MagicMock()
        state.history = [obs]
        tracker._detect_milestones(state, current_iteration=5)
        assert len(tracker.milestones) == 1
        assert tracker.milestones[0].name == "tests_passing"

    def test_no_duplicate_milestones(self):
        from backend.events.observation import CmdOutputObservation

        tracker = ProgressTracker(max_iterations=100)
        obs = CmdOutputObservation(content="passed", command="pytest tests/", exit_code=0)
        state = MagicMock()
        state.history = [obs]
        tracker._detect_milestones(state, 5)
        tracker._detect_milestones(state, 6)
        assert len(tracker.milestones) == 1


# ---------------------------------------------------------------------------
# update (integration)
# ---------------------------------------------------------------------------
class TestUpdate:
    def test_returns_progress_metrics(self):
        tracker = ProgressTracker(max_iterations=100)
        state = MagicMock()
        state.iteration_flag.current_value = 5
        state.history = []
        metrics = tracker.update(state)
        assert isinstance(metrics, ProgressMetrics)
        assert metrics.iterations_completed == 5
        assert metrics.iterations_total == 100
