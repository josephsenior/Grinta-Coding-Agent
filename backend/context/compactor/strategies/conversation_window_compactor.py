"""Compactor that keeps a sliding window of events while preserving file-edit history."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.context.compactor.compactor import Compaction, RollingCompactor
from backend.context.view import View
from backend.ledger.action.agent import CondensationAction
from backend.ledger.action.files import FileEditAction, FileWriteAction
from backend.ledger.action.message import SystemMessageAction
from backend.ledger.event import EventSource
from backend.ledger.observation import Observation

if TYPE_CHECKING:
    from backend.inference.llm_registry import LLMRegistry


class ConversationWindowCompactor(RollingCompactor):
    """Sliding-window compactor that always preserves file-edit events and their paired observations.

    Strategy
    --------
    1. Always keep the most recent ``max_events`` events (recency window).
    2. Outside that window, also keep every ``FileWriteAction`` / ``FileEditAction``
       and any ``Observation`` whose ``.cause`` refers to one of those file actions.
    3. System messages and user messages are always kept regardless of window.
    4. Everything else outside the window is pruned.

    The result is a ``Compaction`` whose ``CondensationAction`` carries the explicit
    list of pruned event IDs (non-contiguous pruning is handled precisely).
    No LLM summary is produced — ``action.summary`` and ``action.summary_offset``
    are always ``None``.
    """

    def __init__(self, max_events: int = 100) -> None:
        self._max_events = max_events
        super().__init__()

    # ------------------------------------------------------------------
    # RollingCompactor interface
    # ------------------------------------------------------------------

    def should_compact(self, view: View) -> bool:
        """Return True when the view is over the event limit or a condensation was requested."""
        if getattr(view, 'unhandled_condensation_request', False):
            return True
        return len(view.events) > self._max_events

    def get_compaction(self, view: View) -> Compaction:
        """Build a Compaction that prunes low-importance old events."""
        events = view.events

        # --- collect file-action ids for paired-observation protection ---
        file_action_ids: set[int] = {
            ev.id
            for ev in events
            if isinstance(ev, (FileWriteAction, FileEditAction))
        }

        # --- build the protected set (must survive pruning) ---
        protected_ids: set[int] = set()
        for ev in events:
            if isinstance(ev, SystemMessageAction):
                protected_ids.add(ev.id)
            elif (
                not isinstance(ev, SystemMessageAction)
                and getattr(ev, 'source', None) == EventSource.USER
            ):
                # Regular user messages
                protected_ids.add(ev.id)
            if isinstance(ev, (FileWriteAction, FileEditAction)):
                protected_ids.add(ev.id)
            elif (
                isinstance(ev, Observation)
                and getattr(ev, 'cause', None) in file_action_ids
            ):
                protected_ids.add(ev.id)

        # --- recency window: last max_events events are always kept ---
        recent_ids: set[int] = {ev.id for ev in events[-self._max_events :]}

        to_keep = protected_ids | recent_ids
        pruned_ids = [ev.id for ev in events if ev.id not in to_keep]

        return Compaction(action=self._create_condensation_action(pruned_ids))

    def compact(self, view: View) -> View | Compaction:
        """Delegate to get_compaction when needed; otherwise return the view unchanged."""
        if self.should_compact(view):
            return self.get_compaction(view)
        return view

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _create_condensation_action(event_ids: list[int]) -> CondensationAction:
        """Build a CondensationAction from a list of event IDs to prune.

        Uses a compact start/end range when the IDs are contiguous, and an
        explicit list otherwise.  The action never carries a summary.
        """
        if event_ids and (max(event_ids) - min(event_ids) + 1 == len(event_ids)):
            return CondensationAction(
                pruned_events_start_id=min(event_ids),
                pruned_events_end_id=max(event_ids),
            )
        return CondensationAction(pruned_event_ids=event_ids)

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_config(
        cls,
        config: Any,
        llm_registry: LLMRegistry,
    ) -> ConversationWindowCompactor:
        """Create from a configuration object."""
        max_events = getattr(config, 'max_events', 100)
        return cls(max_events=max_events)
