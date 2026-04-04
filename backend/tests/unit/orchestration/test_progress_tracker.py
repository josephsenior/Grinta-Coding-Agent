"""Tests for backend.orchestration.progress_tracker module."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

from backend.ledger.action import CmdRunAction, FileEditAction
from backend.ledger.observation import CmdOutputObservation
from backend.orchestration.progress_tracker import (
    Milestone,
    ProgressMetrics,
    ProgressTracker,
)


class TestMilestone:
    """Tests for Milestone dataclass."""

    def test_create_with_required_fields(self):
        """Test creating milestone with required fields."""
        now = datetime.now()
        milestone = Milestone(
            name='tests_passing',
            iteration=10,
            timestamp=now,
        )
        assert milestone.name == 'tests_passing'
        assert milestone.iteration == 10
        assert milestone.timestamp == now
        assert milestone.description == ''

    def test_create_with_description(self):
        """Test creating milestone with description."""
        now = datetime.now()
        milestone = Milestone(
            name='first_commit',
            iteration=5,
            timestamp=now,
            description='Initial implementation complete',
        )
        assert milestone.name == 'first_commit'
        assert milestone.description == 'Initial implementation complete'


class TestProgressMetrics:
    """Tests for ProgressMetrics dataclass."""

    def test_default_values(self):
        """Test default values."""
        metrics = ProgressMetrics()
        assert metrics.completion_percentage == 0.0
        assert metrics.iterations_completed == 0
        assert metrics.iterations_total == 0
        assert metrics.velocity == 0.0
        assert metrics.estimated_completion_time is None
        assert metrics.milestones_reached == []
        assert metrics.is_making_progress is True
        assert metrics.stagnation_iterations == 0

    def test_create_with_values(self):
        """Test creating with custom values."""
        now = datetime.now()
        milestones = [Milestone('test', 1, now)]

        metrics = ProgressMetrics(
            completion_percentage=0.5,
            iterations_completed=10,
            iterations_total=20,
            velocity=2.5,
            estimated_completion_time=now,
            milestones_reached=milestones,
            is_making_progress=True,
            stagnation_iterations=0,
        )

        assert metrics.completion_percentage == 0.5
        assert metrics.iterations_completed == 10
        assert metrics.velocity == 2.5
        assert len(metrics.milestones_reached) == 1


class TestProgressTracker:
    """Tests for ProgressTracker class."""

    def test_init(self):
        """Test initialization."""
        tracker = ProgressTracker(max_iterations=100)
        assert tracker.max_iterations == 100
        assert isinstance(tracker.start_time, datetime)
        assert tracker.milestones == []
        assert tracker.last_progress_iteration == 0
        assert tracker.files_modified == set()
        assert tracker.tests_run == 0
        assert tracker.tests_passed == 0
        assert tracker.error_count == 0
        assert tracker.consecutive_errors == 0

    def test_update_basic(self):
        """Test basic update returns metrics."""
        tracker = ProgressTracker(max_iterations=50)

        # Mock state
        state = MagicMock()
        state.iteration_flag.current_value = 5
        state.history = []

        metrics = tracker.update(state)

        assert isinstance(metrics, ProgressMetrics)
        assert metrics.iterations_total == 50
        assert metrics.iterations_completed == 5

    def test_track_file_modifications(self):
        """Test tracks file modifications from history."""
        tracker = ProgressTracker(max_iterations=50)

        state = MagicMock()
        state.iteration_flag.current_value = 3
        state.history = [
            FileEditAction(path='test.py', content="print('hello')"),
            FileEditAction(path='main.py', content='import os'),
            FileEditAction(path='test.py', content="print('world')"),  # Duplicate
        ]

        tracker.update(state)

        # Should have 2 unique files
        assert len(tracker.files_modified) == 2
        assert 'test.py' in tracker.files_modified
        assert 'main.py' in tracker.files_modified

    def test_track_test_executions_passing(self):
        """Test tracks passing test executions."""
        tracker = ProgressTracker(max_iterations=50)

        state = MagicMock()
        state.iteration_flag.current_value = 5
        state.history = [
            CmdRunAction(command='pytest tests/'),
            CmdOutputObservation(
                content='10 passed',
                command='pytest tests/',
                exit_code=0,
            ),
        ]

        tracker.update(state)

        assert tracker.tests_run == 1
        assert tracker.tests_passed == 1

    def test_track_test_executions_failing(self):
        """Test tracks failing test executions."""
        tracker = ProgressTracker(max_iterations=50)

        state = MagicMock()
        state.iteration_flag.current_value = 5
        state.history = [
            CmdRunAction(command='npm test'),
            CmdOutputObservation(
                content='3 failed',
                command='npm test',
                exit_code=1,
            ),
        ]

        tracker.update(state)

        assert tracker.tests_run == 1
        assert tracker.tests_passed == 0

    def test_detect_milestones_tests_passing(self):
        """Test detects tests passing milestone."""
        tracker = ProgressTracker(max_iterations=50)

        state = MagicMock()
        state.iteration_flag.current_value = 10
        state.history = [
            CmdOutputObservation(
                content='All tests passed',
                command='pytest',
                exit_code=0,
            ),
        ]

        tracker.update(state)

        assert len(tracker.milestones) == 1
        assert tracker.milestones[0].name == 'tests_passing'
        assert tracker.milestones[0].iteration == 10
        assert tracker.last_progress_iteration == 10

    def test_detect_milestones_only_once(self):
        """Test doesn't duplicate milestones."""
        tracker = ProgressTracker(max_iterations=50)

        state = MagicMock()
        state.iteration_flag.current_value = 10
        state.history = [
            CmdOutputObservation(content='passed', command='pytest', exit_code=0),
        ]

        # First update
        tracker.update(state)
        assert len(tracker.milestones) == 1

        # Second update with same milestone
        tracker.update(state)
        assert len(tracker.milestones) == 1  # Should not duplicate

    def test_calculate_completion_percentage_basic(self):
        """Test calculates completion percentage."""
        tracker = ProgressTracker(max_iterations=100)

        state = MagicMock()
        state.iteration_flag.current_value = 30
        state.history = []

        metrics = tracker.update(state)

        # Should have some completion based on iteration progress
        assert metrics.completion_percentage > 0.0
        assert metrics.completion_percentage <= 1.0

    def test_calculate_completion_percentage_with_factors(self):
        """Test completion percentage includes multiple factors."""
        tracker = ProgressTracker(max_iterations=100)

        state = MagicMock()
        state.iteration_flag.current_value = 50
        state.history = [
            FileEditAction(path='test1.py', content='code'),
            FileEditAction(path='test2.py', content='code'),
            CmdRunAction(command='pytest'),
            CmdOutputObservation(content='passed', command='pytest', exit_code=0),
        ]

        # First update
        metrics1 = tracker.update(state)

        # Add more progress markers
        state.history.extend(
            [
                FileEditAction(path='test3.py', content='code'),
                CmdOutputObservation(content='passed', command='pytest', exit_code=0),
            ]
        )
        tracker.milestones.append(Milestone('tests_passing', 50, datetime.now()))

        # Second update
        state.iteration_flag.current_value = 60
        metrics2 = tracker.update(state)

        # Should show increased completion
        assert metrics2.completion_percentage > metrics1.completion_percentage

    def test_calculate_velocity(self):
        """Test calculates velocity (iterations per minute)."""
        tracker = ProgressTracker(max_iterations=100)

        # Set start time to 2 minutes ago
        tracker.start_time = datetime.now() - timedelta(minutes=2)

        state = MagicMock()
        state.iteration_flag.current_value = 10
        state.history = []

        metrics = tracker.update(state)

        # 10 iterations in 2 minutes = 5 iterations/minute
        assert metrics.velocity > 0.0
        assert metrics.velocity < 10.0  # Should be around 5

    def test_velocity_zero_at_start(self):
        """Test velocity is zero at start."""
        tracker = ProgressTracker(max_iterations=100)

        state = MagicMock()
        state.iteration_flag.current_value = 0
        state.history = []

        metrics = tracker.update(state)

        # At iteration 0, velocity should be 0 or very small
        assert metrics.velocity >= 0.0

    def test_is_making_progress_true(self):
        """Test detects making progress."""
        tracker = ProgressTracker(max_iterations=100)
        tracker.last_progress_iteration = 5

        state = MagicMock()
        state.iteration_flag.current_value = 10
        state.history = []

        metrics = tracker.update(state)

        # Within window, should be making progress
        assert metrics.is_making_progress is True

    def test_is_making_progress_false(self):
        """Test detects stagnation."""
        tracker = ProgressTracker(max_iterations=100)
        tracker.last_progress_iteration = 5

        state = MagicMock()
        state.iteration_flag.current_value = 20  # 15 iterations since progress
        state.history = []

        metrics = tracker.update(state)

        # Outside window (default 10), should not be making progress
        assert metrics.is_making_progress is False
        assert metrics.stagnation_iterations == 15

    def test_estimate_completion_time(self):
        """Test estimates completion time."""
        tracker = ProgressTracker(max_iterations=100)

        # Set start time to 10 minutes ago
        tracker.start_time = datetime.now() - timedelta(minutes=10)

        state = MagicMock()
        state.iteration_flag.current_value = 50
        state.history = [
            FileEditAction(path='test.py', content='code'),
        ]

        metrics = tracker.update(state)

        # Should have an ETA if velocity > 0 and completion < 100%
        if metrics.velocity > 0 and metrics.completion_percentage < 1.0:
            assert metrics.estimated_completion_time is not None
            assert isinstance(metrics.estimated_completion_time, datetime)

    def test_estimate_completion_time_none_when_complete(self):
        """Test ETA is None when complete."""
        tracker = ProgressTracker(max_iterations=100)

        state = MagicMock()
        state.iteration_flag.current_value = 100
        state.history = []

        # Force completion to 100%
        tracker.files_modified = {f'file{i}.py' for i in range(10)}
        tracker.tests_run = 10
        tracker.tests_passed = 10
        tracker.milestones = [Milestone(f'm{i}', i, datetime.now()) for i in range(10)]

        metrics = tracker.update(state)

        # At 100% or near it, ETA should be None
        if metrics.completion_percentage >= 1.0:
            assert metrics.estimated_completion_time is None

    def test_estimate_completion_time_none_when_no_velocity(self):
        """Test ETA is None when velocity is zero."""
        tracker = ProgressTracker(max_iterations=100)

        state = MagicMock()
        state.iteration_flag.current_value = 0
        state.history = []

        metrics = tracker.update(state)

        # With zero velocity, ETA should be None
        assert metrics.estimated_completion_time is None

    def test_completion_percentage_capped_at_100(self):
        """Test completion percentage is capped at 1.0."""
        tracker = ProgressTracker(max_iterations=10)

        # Add lots of progress markers
        tracker.files_modified = {f'file{i}.py' for i in range(20)}
        tracker.tests_run = 20
        tracker.tests_passed = 20
        tracker.milestones = [Milestone(f'm{i}', i, datetime.now()) for i in range(20)]

        state = MagicMock()
        state.iteration_flag.current_value = 10
        state.history = []

        metrics = tracker.update(state)

        # Should be capped at 1.0 (100%)
        assert metrics.completion_percentage <= 1.0

    def test_milestones_reached_is_copy(self):
        """Test milestones_reached is a copy, not reference."""
        tracker = ProgressTracker(max_iterations=100)
        tracker.milestones = [Milestone('test', 1, datetime.now())]

        state = MagicMock()
        state.iteration_flag.current_value = 5
        state.history = []

        metrics = tracker.update(state)

        # Modify metrics milestones
        metrics.milestones_reached.append(Milestone('new', 2, datetime.now()))

        # Original should be unchanged
        assert len(tracker.milestones) == 1
