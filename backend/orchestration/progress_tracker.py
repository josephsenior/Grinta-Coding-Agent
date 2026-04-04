"""Progress tracking for autonomous agent runs.

Monitors agent progress in real-time to:
- Calculate completion percentage
- Detect stagnation
- Estimate time to completion
- Provide progress visibility
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.orchestration.state.state import State

from backend.core.logger import app_logger as logger
from backend.ledger.action import (
    CmdRunAction,
    FileEditAction,
)
from backend.ledger.observation import CmdOutputObservation


@dataclass
class Milestone:
    """Represents a progress milestone."""

    name: str
    iteration: int
    timestamp: datetime
    description: str = ''


@dataclass
class ProgressMetrics:
    """Current progress metrics."""

    completion_percentage: float = 0.0
    iterations_completed: int = 0
    iterations_total: int = 0
    velocity: float = 0.0  # Iterations per minute
    estimated_completion_time: datetime | None = None
    milestones_reached: list[Milestone] = field(default_factory=list)
    is_making_progress: bool = True
    stagnation_iterations: int = 0


class ProgressTracker:
    """Tracks autonomous agent progress in real-time.

    Monitors various signals:
    - Task tracker updates
    - File modifications
    - Test executions
    - Git commits
    - Error rates
    """

    def __init__(self, max_iterations: int) -> None:
        """Initialize progress tracker.

        Args:
            max_iterations: Maximum allowed iterations

        """
        self.max_iterations = max_iterations
        self.start_time = datetime.now()
        self.milestones: list[Milestone] = []
        self.last_progress_iteration = 0
        self.files_modified: set[str] = set()
        self.tests_run = 0
        self.tests_passed = 0
        self.error_count = 0
        self.consecutive_errors = 0

        logger.info(
            'ProgressTracker initialized with max_iterations=%s', max_iterations
        )

    def update(self, state: State) -> ProgressMetrics:
        """Update progress based on current state.

        Args:
            state: Current agent state

        Returns:
            Updated progress metrics

        """
        current_iteration = state.iteration_flag.current_value

        # Track file modifications
        self._track_file_modifications(state)

        # Track test executions
        self._track_test_executions(state)

        # Detect milestones
        self._detect_milestones(state, current_iteration)

        # Calculate completion percentage
        completion_pct = self._calculate_completion_percentage(state)

        # Calculate velocity
        velocity = self._calculate_velocity(current_iteration)

        # Check if making progress
        is_making_progress = self._is_making_progress(current_iteration)

        # Calculate stagnation
        stagnation_iters = current_iteration - self.last_progress_iteration

        # Estimate completion time
        eta = self._estimate_completion_time(completion_pct, velocity)

        return ProgressMetrics(
            completion_percentage=completion_pct,
            iterations_completed=current_iteration,
            iterations_total=self.max_iterations,
            velocity=velocity,
            estimated_completion_time=eta,
            milestones_reached=self.milestones.copy(),
            is_making_progress=is_making_progress,
            stagnation_iterations=stagnation_iters,
        )

    def _track_file_modifications(self, state: State) -> None:
        """Track file modifications in history.

        Args:
            state: Current state

        """
        # Look at recent history
        recent_history = state.history[-10:]

        for event in recent_history:
            if isinstance(event, FileEditAction):
                self.files_modified.add(event.path)

    def _track_test_executions(self, state: State) -> None:
        """Track test executions and results.

        Args:
            state: Current state

        """
        recent_history = state.history[-10:]

        for i, event in enumerate(recent_history):
            if isinstance(event, CmdRunAction):
                if any(
                    test_cmd in event.command.lower()
                    for test_cmd in ['pytest', 'npm test', 'jest']
                ):
                    # Look for observation
                    for j in range(i + 1, min(i + 5, len(recent_history))):
                        next_event = recent_history[j]
                        if isinstance(next_event, CmdOutputObservation):
                            self.tests_run += 1
                            if next_event.exit_code == 0:
                                self.tests_passed += 1
                            break

    def _detect_milestones(self, state: State, current_iteration: int) -> None:
        """Detect and record progress milestones.

        Args:
            state: Current state
            current_iteration: Current iteration number

        """
        # Check for milestone events
        recent_history = state.history[-5:]

        for event in recent_history:
            # Test passing milestone
            if isinstance(event, CmdOutputObservation):
                if 'pytest' in event.command and event.exit_code == 0:
                    if not any(m.name == 'tests_passing' for m in self.milestones):
                        self.milestones.append(
                            Milestone(
                                name='tests_passing',
                                iteration=current_iteration,
                                timestamp=datetime.now(),
                                description='All tests passing',
                            ),
                        )
                        self.last_progress_iteration = current_iteration

    def _calculate_completion_percentage(self, state: State) -> float:
        """Calculate task completion percentage.

        Args:
            state: Current state

        Returns:
            Completion percentage (0.0 to 1.0)

        """
        # Weighted factors
        factors = {
            'iteration_progress': (
                state.iteration_flag.current_value / self.max_iterations
            )
            * 0.3,
            'files_modified': min(len(self.files_modified) / 5.0, 1.0)
            * 0.2,  # Cap at 5 files
            'tests_passing': (self.tests_passed / max(self.tests_run, 1)) * 0.3
            if self.tests_run > 0
            else 0.0,
            'milestones': (len(self.milestones) / 5.0) * 0.2,  # Cap at 5 milestones
        }

        total = sum(factors.values())
        return min(total, 1.0)  # Cap at 100%

    def _calculate_velocity(self, current_iteration: int) -> float:
        """Calculate velocity (iterations per minute).

        Args:
            current_iteration: Current iteration number

        Returns:
            Velocity in iterations per minute

        """
        elapsed_seconds = (datetime.now() - self.start_time).total_seconds()
        if elapsed_seconds < 1:
            return 0.0

        elapsed_minutes = elapsed_seconds / 60.0
        return current_iteration / elapsed_minutes if elapsed_minutes > 0 else 0.0

    def _is_making_progress(self, current_iteration: int, window: int = 10) -> bool:
        """Check if agent made progress in last N iterations.

        Args:
            current_iteration: Current iteration number
            window: Look-back window

        Returns:
            True if making progress

        """
        # Check if any progress markers updated recently
        iterations_since_progress = current_iteration - self.last_progress_iteration

        return iterations_since_progress < window

    def _estimate_completion_time(
        self, completion_pct: float, velocity: float
    ) -> datetime | None:
        """Estimate completion time based on current progress and velocity.

        Args:
            completion_pct: Current completion percentage
            velocity: Current velocity (iterations per minute)

        Returns:
            Estimated completion datetime or None

        """
        if velocity <= 0 or completion_pct >= 1.0:
            return None

        remaining_pct = 1.0 - completion_pct
        remaining_iterations = self.max_iterations * remaining_pct
        minutes_remaining = (
            remaining_iterations / velocity if velocity > 0 else float('inf')
        )

        if minutes_remaining > 10000:  # More than a week
            return None

        from datetime import timedelta

        return datetime.now() + timedelta(minutes=minutes_remaining)
