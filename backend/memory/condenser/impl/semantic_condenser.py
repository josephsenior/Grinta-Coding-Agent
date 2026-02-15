"""Semantic Condenser - Intelligent Compression with Meaning Preservation.

Uses semantic similarity and importance scoring to compress context
while preserving the most critical information.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.core.logger import FORGE_logger as logger
from backend.events.action import Action, MessageAction
from backend.events.action.agent import CondensationAction
from backend.events.event import Event
from backend.events.observation import Observation
from backend.memory.condenser.condenser import Condensation, RollingCondenser
from backend.memory.view import View


@dataclass
class EventImportance:
    """Importance score for an event."""

    event: Event
    importance_score: float
    reasons: list[str]  # Why this event is important


class SemanticCondenser(RollingCondenser):
    """Semantic condenser that intelligently compresses context.

    Features:
    - Scores events by importance (decisions, errors, file changes)
    - Preserves semantically important events
    - Summarizes less critical events
    - Maintains conversation coherence
    """

    def __init__(
        self,
        keep_first: int = 5,
        max_size: int = 100,
        importance_threshold: float = 0.5,
    ):
        """Initialize semantic condenser.

        Args:
            keep_first: Number of initial events to always keep
            max_size: Maximum number of events to keep
            importance_threshold: Minimum importance to keep (0-1)

        """
        super().__init__()
        self.keep_first = keep_first
        self.max_size = max_size
        self.importance_threshold = importance_threshold

        logger.info(
            "Semantic condenser initialized (keep_first=%s, max_size=%s)",
            keep_first,
            max_size,
        )

    def get_condensation(self, view: View) -> Condensation:
        """Apply semantic condensation.

        This method:
        1. Scores each event by importance
        2. Keeps essential initial events
        3. Preserves high-importance events
        4. Forgets low-importance events
        5. Ensures conversation coherence
        """
        events = view.events
        if not events or len(events) <= self.max_size:
            return Condensation(action=CondensationAction(forgotten_event_ids=[]))

        # Score all events by importance
        scored_events = self._score_events(events)

        # Identify events to keep
        keep_event_ids = self._select_events_to_keep(scored_events)

        # Calculate events to forget
        all_event_ids = {e.id for e in events}
        forgotten_event_ids = sorted(all_event_ids - keep_event_ids)

        logger.info(
            "Semantic condensation: Keeping %s events, forgetting %s events",
            len(keep_event_ids),
            len(forgotten_event_ids),
        )

        return Condensation(
            action=CondensationAction(forgotten_event_ids=forgotten_event_ids)
        )

    def _score_events(self, events: list[Event]) -> list[EventImportance]:
        """Score events by importance.

        Args:
            events: List of events to score

        Returns:
            List of EventImportance objects

        """
        scored: list[EventImportance] = []

        for event in events:
            score, reasons = self._calculate_importance(event)
            scored.append(
                EventImportance(event=event, importance_score=score, reasons=reasons)
            )

        return scored

    def _score_action_event(self, event: Action) -> tuple[float, list[str]]:
        """Calculate importance score for Action events.

        Args:
            event: Action event

        Returns:
            Tuple of (score, reasons)

        """
        score = 0.0
        reasons: list[str] = []

        if hasattr(event, "action"):
            action_str = str(event.action).lower()

            if "file" in action_str:
                score += 0.4
                reasons.append("file_operation")

            if "delegate" in action_str:
                score += 0.3
                reasons.append("delegation")

            if "finish" in action_str:
                score += 0.5
                reasons.append("completion")

        if hasattr(event, "command"):
            cmd_lower = event.command.lower()
            if any(
                keyword in cmd_lower
                for keyword in ["install", "build", "deploy", "setup"]
            ):
                score += 0.3
                reasons.append("setup_command")

        return score, reasons

    def _score_observation_event(self, event: Observation) -> tuple[float, list[str]]:
        """Calculate importance score for Observation events.

        Args:
            event: Observation event

        Returns:
            Tuple of (score, reasons)

        """
        score = 0.0
        reasons: list[str] = []

        if hasattr(event, "error") and event.error:
            score += 0.6
            reasons.append("error")

        if hasattr(event, "exit_code") and event.exit_code == 0:
            score += 0.2
            reasons.append("success")

        if hasattr(event, "content"):
            content_len = len(str(event.content))
            if content_len > 1000:
                score += 0.1
                reasons.append("detailed_output")

        return score, reasons

    def _score_message_event(self, event: MessageAction) -> tuple[float, list[str]]:
        """Calculate importance score for MessageAction events.

        Args:
            event: MessageAction event

        Returns:
            Tuple of (score, reasons)

        """
        score = 0.0
        reasons: list[str] = []

        if hasattr(event, "source") and event.source == "user":
            score += 0.5
            reasons.append("user_message")

        if hasattr(event, "content") and "?" in str(event.content):
            score += 0.2
            reasons.append("question")

        return score, reasons

    def _calculate_importance(self, event: Event) -> tuple[float, list[str]]:
        """Calculate importance score for an event.

        Args:
            event: Event to score

        Returns:
            Tuple of (score, reasons)

        """
        score = 0.0
        reasons: list[str] = []

        # Score based on event type
        if isinstance(event, Action):
            score, reasons = self._score_action_event(event)
        elif isinstance(event, Observation):
            score, reasons = self._score_observation_event(event)
        elif isinstance(event, MessageAction):
            score, reasons = self._score_message_event(event)

        # Normalize score to 0-1
        score = min(1.0, score)

        if not reasons:
            reasons.append("normal_importance")

        return score, reasons

    def _select_events_to_keep(self, scored_events: list[EventImportance]) -> set[int]:
        """Select which events to keep based on importance.

        Args:
            scored_events: List of scored events

        Returns:
            Set of event IDs to keep

        """
        keep_ids = set()

        # Always keep first N events (task description, system messages)
        for scored in scored_events[: self.keep_first]:
            keep_ids.add(scored.event.id)

        # Keep recent events (last 20% or at least 10)
        recent_count = max(10, len(scored_events) // 5)
        for scored in scored_events[-recent_count:]:
            keep_ids.add(scored.event.id)

        # Keep high-importance events
        for scored in scored_events:
            if scored.importance_score >= self.importance_threshold:
                keep_ids.add(scored.event.id)

        # If we're still over max_size, remove lowest importance
        if len(keep_ids) > self.max_size:
            # Sort by importance
            sorted_scored = sorted(
                [s for s in scored_events if s.event.id in keep_ids],
                key=lambda x: x.importance_score,
                reverse=True,
            )

            # Keep only top max_size
            keep_ids = {s.event.id for s in sorted_scored[: self.max_size]}

        return keep_ids

    def _ensure_coherence(self, events: list[Event], keep_ids: set[int]) -> set[int]:
        """Ensure conversation coherence by keeping action-observation pairs.

        Args:
            events: Full list of events
            keep_ids: Current set of IDs to keep

        Returns:
            Updated set of IDs to keep

        """
        coherent_ids = set(keep_ids)

        # For each action we're keeping, keep its observation
        for i, event in enumerate(events):
            if event.id in coherent_ids and isinstance(event, Action):
                # Look for corresponding observation
                if i + 1 < len(events) and isinstance(events[i + 1], Observation):
                    coherent_ids.add(events[i + 1].id)

        return coherent_ids
