from __future__ import annotations

from typing import TYPE_CHECKING

from backend.controller.stuck import StuckDetector

if TYPE_CHECKING:
    from backend.controller.agent_controller import AgentController
    from backend.controller.state.state import State


class StuckDetectionService:
    """Provides stuck detection utilities for the agent controller."""

    def __init__(self, controller: AgentController) -> None:
        self._controller = controller
        self._detector: StuckDetector | None = None

    def initialize(self, state: State) -> None:
        """Initialize detector for the given state."""
        self._detector = StuckDetector(state)

    def is_stuck(self) -> bool:
        """Return True if the controller (or any delegate) appears stuck."""
        delegate = getattr(self._controller, "delegate", None)
        if delegate is not None:
            stuck_service = getattr(delegate, "stuck_service", None)
            if stuck_service is not None:
                result = stuck_service.is_stuck()
                if result is True:
                    return True

        if not self._detector:
            return False
        return bool(self._detector.is_stuck(self._controller.headless_mode))

    def compute_repetition_score(self) -> float:
        """Compute a 0.0-1.0 proximity score for stuck detection.

        Exposes how close the agent is to being flagged as stuck,
        allowing proactive self-correction.
        """
        if not self._detector:
            return 0.0
        try:
            return self._detector.compute_repetition_score(self._controller.headless_mode)
        except Exception:
            return 0.0
