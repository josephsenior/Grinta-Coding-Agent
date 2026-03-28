"""Utilities for replaying previously captured agent trajectories.

Enhanced with determinism verification: after each replayed action the
manager can compare the actual observation against the original trajectory
observation and flag divergence.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from backend.core.logger import forge_logger as logger
from backend.ledger.action.action import Action
from backend.ledger.action.message import MessageAction
from backend.ledger.event import Event, EventSource
from backend.ledger.observation.empty import NullObservation
from backend.ledger.serialization.event import event_from_dict


@dataclass
class ReplayDivergence:
    """Records a divergence between expected and actual observations."""

    index: int
    action_type: str
    expected_hash: str
    actual_hash: str
    message: str


class ReplayManager:
    """ReplayManager manages the lifecycle of a replay session of a given trajectory.

    Replay manager keeps track of a list of events, replays actions, and ignore
    messages and observations.

    Enhanced features:
    - Determinism verification via observation content hashing
    - Divergence tracking and reporting
    - Snapshot comparison callbacks

    Note that unexpected or even erroneous results could happen if
    1) any action is non-deterministic, OR
    2) if the initial state before the replay session is different from the
    initial state of the trajectory.
    """

    def __init__(self, events: list[Event] | None) -> None:
        """Normalise the supplied events and prime replay mode state."""
        replay_events = []
        for event in events or []:
            if event.source == EventSource.ENVIRONMENT:
                continue
            if isinstance(event, NullObservation):
                continue
            replay_events.append(event)
        if replay_events:
            logger.info("Replay events loaded, events length = %s", len(replay_events))
            for index in range(len(replay_events) - 1):
                event = replay_events[index]
                if isinstance(event, MessageAction) and event.wait_for_response:
                    logger.info(
                        "Replay events contains wait_for_response message action, ignoring wait_for_response"
                    )
                    event.wait_for_response = False
        self.replay_events = replay_events
        self.replay_mode = bool(replay_events)
        self.replay_index = 0
        # Determinism tracking
        self._divergences: list[ReplayDivergence] = []
        self._verify_determinism = True

    @property
    def divergences(self) -> list[ReplayDivergence]:
        """Return all observed divergences during replay."""
        return list(self._divergences)

    @property
    def is_deterministic(self) -> bool:
        """Return True if no divergences have been observed."""
        return not self._divergences

    def _replayable(self) -> bool:
        return (
            self.replay_events is not None
            and self.replay_index < len(self.replay_events)
            and isinstance(self.replay_events[self.replay_index], Action)
        )

    def should_replay(self) -> bool:
        """Whether the controller is in trajectory replay mode, and the replay.

        hasn't finished. Note: after the replay is finished, the user and
        the agent could continue to message/act.

        This method also moves "replay_index" to the next action, if applicable.
        """
        if not self.replay_mode:
            return False
        assert self.replay_events is not None
        while self.replay_index < len(self.replay_events) and (not self._replayable()):
            self.replay_index += 1
        return self._replayable()

    def step(self) -> Action:
        """Get next action from replay trajectory.

        Returns:
            Next action to replay

        """
        assert self.replay_events is not None
        event = self.replay_events[self.replay_index]
        if not isinstance(event, Action):
            raise RuntimeError(
                f"Unexpected non-action event in replay at index {self.replay_index}: {type(event).__name__}"
            )
        self.replay_index += 1
        return event

    def verify_observation(self, actual_observation: Event | None) -> bool:
        """Compare actual observation against the trajectory's expected observation.

        Call this after executing the replayed action. Returns True if the
        observations match (or if verification is disabled / no expected
        observation exists).
        """
        if not self._verify_determinism or not self.replay_events:
            return True

        # Look for the expected observation at or after the current replay_index
        expected = self._peek_expected_observation()
        if expected is None:
            return True

        expected_hash = self._content_hash(expected)
        actual_hash = self._content_hash(actual_observation)

        if expected_hash != actual_hash:
            action_idx = self.replay_index - 1
            action_type = (
                type(self.replay_events[action_idx]).__name__
                if 0 <= action_idx < len(self.replay_events)
                else "unknown"
            )
            divergence = ReplayDivergence(
                index=action_idx,
                action_type=action_type,
                expected_hash=expected_hash,
                actual_hash=actual_hash,
                message=f"Replay divergence at index {action_idx}: "
                f"expected hash {expected_hash[:8]}, got {actual_hash[:8]}",
            )
            self._divergences.append(divergence)
            logger.warning(divergence.message)
            return False

        return True

    def snapshot(self) -> dict[str, Any]:
        """Diagnostic snapshot for debug endpoints."""
        return {
            "replay_mode": self.replay_mode,
            "replay_index": self.replay_index,
            "total_events": len(self.replay_events) if self.replay_events else 0,
            "divergence_count": len(self._divergences),
            "is_deterministic": self.is_deterministic,
        }

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #

    def _peek_expected_observation(self) -> Event | None:
        """Find the next non-action event after the current action."""
        if not self.replay_events:
            return None
        idx = self.replay_index
        while idx < len(self.replay_events):
            ev = self.replay_events[idx]
            if not isinstance(ev, Action):
                return ev
            break  # Next action found without an observation in between
        return None

    @staticmethod
    def _content_hash(event: Event | None) -> str:
        """Hash the content of an event for comparison."""
        if event is None:
            return "none"
        content = getattr(event, "content", "")
        if content is None:
            content = ""
        return hashlib.sha256(str(content).encode()).hexdigest()

    @staticmethod
    def get_replay_events(trajectory: Iterable[Mapping[str, Any]]) -> list[Event]:
        """Convert trajectory list to event objects for replay.

        Args:
            trajectory: List of event dictionaries

        Returns:
            List of event objects

        Raises:
            ValueError: If trajectory format is invalid

        """
        replay_events: list[Event] = []
        for item in trajectory:
            event = event_from_dict(dict(item))
            if event.source == EventSource.ENVIRONMENT:
                continue
            event._id = None
            replay_events.append(event)
        return replay_events
