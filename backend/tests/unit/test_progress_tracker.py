"""Unit tests for backend.controller.progress_tracker — Progress monitoring."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from backend.controller.progress_tracker import (
    Milestone,
    ProgressMetrics,
    ProgressTracker,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_state(iteration=1, history=None):
    """Build a mock State-like object."""
    state = MagicMock()
    state.iteration_flag = MagicMock(current_value=iteration)
    state.history = history or []
    return state


def _make_file_edit_action(path="test.py"):
    """Build a mock FileEditAction."""
    from backend.events.action import FileEditAction

    action = MagicMock(spec=FileEditAction)
    action.path = path
    # Make isinstance checks work
    action.__class__ = FileEditAction
    return action


def _make_cmd_run_action(command="echo hello"):
    """Build a mock CmdRunAction."""
    from backend.events.action import CmdRunAction

    action = MagicMock(spec=CmdRunAction)
    action.command = command
    action.__class__ = CmdRunAction
    return action


def _make_cmd_output_observation(command="echo hello", exit_code=0):
    """Build a mock CmdOutputObservation."""
    from backend.events.observation import CmdOutputObservation

    obs = MagicMock(spec=CmdOutputObservation)
    obs.command = command
    obs.exit_code = exit_code
    obs.__class__ = CmdOutputObservation
    return obs


# ---------------------------------------------------------------------------
# Milestone & ProgressMetrics dataclasses
# ---------------------------------------------------------------------------


class TestMilestone:
    def test_creation(self):
        m = Milestone(
            name="tests_passing",
            iteration=5,
            timestamp=datetime.now(),
            description="All tests pass",
        )
        assert m.name == "tests_passing"
        assert m.iteration == 5

    def test_default_description(self):
        m = Milestone(name="test", iteration=1, timestamp=datetime.now())
        assert m.description == ""


class TestProgressMetrics:
    def test_defaults(self):
        pm = ProgressMetrics()
        assert pm.completion_percentage == 0.0
        assert pm.iterations_completed == 0
        assert pm.is_making_progress is True
        assert pm.stagnation_iterations == 0
        assert pm.milestones_reached == []


# ---------------------------------------------------------------------------
# ProgressTracker — initialization
# ---------------------------------------------------------------------------


class TestTrackerInit:
    def test_basic_init(self):
        tracker = ProgressTracker(max_iterations=100)
        assert tracker.max_iterations == 100
        assert tracker.files_modified == set()
        assert tracker.tests_run == 0
        assert tracker.tests_passed == 0
        assert tracker.error_count == 0

    def test_start_time_set(self):
        before = datetime.now()
        tracker = ProgressTracker(max_iterations=50)
        after = datetime.now()
        assert before <= tracker.start_time <= after


# ---------------------------------------------------------------------------
# File modification tracking
# ---------------------------------------------------------------------------


class TestFileModTracking:
    def test_tracks_file_edits_in_history(self):
        tracker = ProgressTracker(max_iterations=100)
        file_action = _make_file_edit_action("src/main.py")
        state = _mock_state(iteration=1, history=[file_action])
        tracker._track_file_modifications(state)
        assert "src/main.py" in tracker.files_modified

    def test_deduplicates_file_modifications(self):
        tracker = ProgressTracker(max_iterations=100)
        actions = [
            _make_file_edit_action("file.py"),
            _make_file_edit_action("file.py"),
            _make_file_edit_action("file.py"),
        ]
        state = _mock_state(history=actions)
        tracker._track_file_modifications(state)
        assert len(tracker.files_modified) == 1


# ---------------------------------------------------------------------------
# Test execution tracking
# ---------------------------------------------------------------------------


class TestTestTracking:
    def test_tracks_passing_test(self):
        tracker = ProgressTracker(max_iterations=100)
        cmd = _make_cmd_run_action("pytest -v")
        obs = _make_cmd_output_observation("pytest -v", exit_code=0)
        state = _mock_state(history=[cmd, obs])
        tracker._track_test_executions(state)
        assert tracker.tests_run == 1
        assert tracker.tests_passed == 1

    def test_tracks_failing_test(self):
        tracker = ProgressTracker(max_iterations=100)
        cmd = _make_cmd_run_action("pytest -v")
        obs = _make_cmd_output_observation("pytest -v", exit_code=1)
        state = _mock_state(history=[cmd, obs])
        tracker._track_test_executions(state)
        assert tracker.tests_run == 1
        assert tracker.tests_passed == 0


# ---------------------------------------------------------------------------
# Velocity calculation
# ---------------------------------------------------------------------------


class TestVelocity:
    def test_zero_velocity_at_start(self):
        tracker = ProgressTracker(max_iterations=100)
        v = tracker._calculate_velocity(0)
        assert v == 0.0

    def test_positive_velocity_after_time(self):
        tracker = ProgressTracker(max_iterations=100)
        tracker.start_time = datetime.now() - timedelta(minutes=2)
        v = tracker._calculate_velocity(10)
        assert v > 0
        assert v == pytest.approx(5.0, rel=0.1)  # ~10 iterations / 2 min


# ---------------------------------------------------------------------------
# Progress detection
# ---------------------------------------------------------------------------


class TestProgressDetection:
    def test_making_progress_when_recent(self):
        tracker = ProgressTracker(max_iterations=100)
        tracker.last_progress_iteration = 5
        assert tracker._is_making_progress(6) is True

    def test_not_making_progress_when_stagnant(self):
        tracker = ProgressTracker(max_iterations=100)
        tracker.last_progress_iteration = 0
        assert tracker._is_making_progress(15) is False  # >10 iterations since

    def test_custom_window(self):
        tracker = ProgressTracker(max_iterations=100)
        tracker.last_progress_iteration = 0
        assert tracker._is_making_progress(5, window=3) is False
        assert tracker._is_making_progress(2, window=3) is True


# ---------------------------------------------------------------------------
# Completion percentage
# ---------------------------------------------------------------------------


class TestCompletionPercentage:
    def test_zero_at_start(self):
        tracker = ProgressTracker(max_iterations=100)
        state = _mock_state(iteration=0)
        pct = tracker._calculate_completion_percentage(state)
        assert pct == 0.0

    def test_capped_at_one(self):
        tracker = ProgressTracker(max_iterations=10)
        tracker.files_modified = {f"file{i}.py" for i in range(20)}
        tracker.tests_run = 10
        tracker.tests_passed = 10
        tracker.milestones = [
            Milestone(name=f"m{i}", iteration=i, timestamp=datetime.now())
            for i in range(10)
        ]
        state = _mock_state(iteration=10)
        pct = tracker._calculate_completion_percentage(state)
        assert pct <= 1.0


# ---------------------------------------------------------------------------
# ETA estimation
# ---------------------------------------------------------------------------


class TestETAEstimation:
    def test_eta_none_when_velocity_zero(self):
        tracker = ProgressTracker(max_iterations=100)
        eta = tracker._estimate_completion_time(0.5, 0.0)
        assert eta is None

    def test_eta_none_when_complete(self):
        tracker = ProgressTracker(max_iterations=100)
        eta = tracker._estimate_completion_time(1.0, 5.0)
        assert eta is None

    def test_eta_in_future(self):
        tracker = ProgressTracker(max_iterations=100)
        eta = tracker._estimate_completion_time(0.5, 10.0)
        assert eta is not None
        assert eta > datetime.now()

    def test_eta_none_when_too_far(self):
        tracker = ProgressTracker(max_iterations=100)
        # Very low velocity
        eta = tracker._estimate_completion_time(0.01, 0.00001)
        assert eta is None  # > 10000 minutes


# ---------------------------------------------------------------------------
# Milestone detection
# ---------------------------------------------------------------------------


class TestMilestoneDetection:
    def test_detects_test_passing_milestone(self):
        tracker = ProgressTracker(max_iterations=100)
        obs = _make_cmd_output_observation("pytest", exit_code=0)
        state = _mock_state(iteration=5, history=[obs])
        tracker._detect_milestones(state, 5)
        assert any(m.name == "tests_passing" for m in tracker.milestones)
        assert tracker.last_progress_iteration == 5

    def test_no_duplicate_milestones(self):
        tracker = ProgressTracker(max_iterations=100)
        obs = _make_cmd_output_observation("pytest", exit_code=0)
        state = _mock_state(iteration=5, history=[obs])
        tracker._detect_milestones(state, 5)
        tracker._detect_milestones(state, 6)
        tests_milestones = [m for m in tracker.milestones if m.name == "tests_passing"]
        assert len(tests_milestones) == 1


# ---------------------------------------------------------------------------
# Full update cycle
# ---------------------------------------------------------------------------


class TestUpdate:
    def test_returns_progress_metrics(self):
        tracker = ProgressTracker(max_iterations=100)
        state = _mock_state(iteration=1)
        pm = tracker.update(state)
        assert isinstance(pm, ProgressMetrics)
        assert pm.iterations_completed == 1
        assert pm.iterations_total == 100

    def test_stagnation_detection(self):
        tracker = ProgressTracker(max_iterations=100)
        tracker.last_progress_iteration = 0
        state = _mock_state(iteration=20)
        pm = tracker.update(state)
        assert pm.stagnation_iterations == 20
        assert pm.is_making_progress is False
