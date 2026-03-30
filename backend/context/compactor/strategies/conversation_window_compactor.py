"""Compactor implementation that preserves key conversation anchors while trimming history."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.core.config.compactor_config import ConversationWindowCompactorConfig
from backend.core.logger import app_logger as logger
from backend.ledger.action.agent import CondensationAction, RecallAction
from backend.ledger.action.files import FileEditAction, FileWriteAction
from backend.ledger.action.message import MessageAction, SystemMessageAction
from backend.ledger.event import EventSource
from backend.ledger.observation import Observation
from backend.context.compactor.compactor import Compaction, RollingCompactor
from backend.context.view import View

if TYPE_CHECKING:
    from backend.inference.llm_registry import LLMRegistry


class ConversationWindowCompactor(RollingCompactor):
    """Compactor that trims conversation history while preserving critical first events."""

    def __init__(self, max_events: int = 100) -> None:
        """Initialize the rolling compactor base state."""
        super().__init__()
        self._max_events = max_events

    def compact(self, view: View) -> View | Compaction:
        """Compact, then condense if thresholds are exceeded."""
        if self.should_compact(view):
            return self.get_compaction(view)
        return view

    def _find_essential_events(
        self,
        events: list,
    ) -> tuple[
        SystemMessageAction | None,
        MessageAction | None,
        RecallAction | None,
        Observation | None,
    ]:
        """Find essential events: system message, first user message, and recall action/observation."""
        system_message = next(
            (e for e in events if isinstance(e, SystemMessageAction)), None
        )
        first_user_msg = next(
            (
                e
                for e in events
                if isinstance(e, MessageAction) and e.source == EventSource.USER
            ),
            None,
        )

        if first_user_msg is None:
            return system_message, None, None, None

        first_user_msg_index = next(
            (
                i
                for i, event in enumerate(events)
                if isinstance(event, MessageAction) and event.source == EventSource.USER
            ),
            -1,
        )
        recall_action, recall_observation = self._find_recall_and_observation(
            events,
            first_user_msg.content,
            first_user_msg_index + 1,
        )

        return system_message, first_user_msg, recall_action, recall_observation

    def _build_essential_events_list(
        self,
        system_message: SystemMessageAction | None,
        first_user_msg: MessageAction | None,
        recall_action: RecallAction | None,
        recall_observation: Observation | None,
    ) -> list[int]:
        """Build list of essential event IDs that must be preserved."""
        essential_events: list[int] = []

        if system_message:
            essential_events.append(system_message.id)

        if first_user_msg:
            essential_events.append(first_user_msg.id)

        if recall_action:
            essential_events.append(recall_action.id)
            if recall_observation:
                essential_events.append(recall_observation.id)

        return essential_events

    def _calculate_recent_events_slice(
        self, events: list, essential_events: list[int]
    ) -> tuple[list, int]:
        """Calculate which recent events to keep and find the first valid event index."""
        num_essential_events = len(essential_events)
        total_events = len(events)
        num_non_essential_events = total_events - num_essential_events
        num_recent_to_keep = max(1, num_non_essential_events // 2)

        slice_start_index = max(0, total_events - num_recent_to_keep)
        recent_events_slice = events[slice_start_index:]

        first_valid_event_index_in_slice = next(
            (
                i
                for i, event in enumerate(recent_events_slice)
                if not isinstance(event, Observation)
            ),
            len(recent_events_slice),
        )

        if first_valid_event_index_in_slice == len(recent_events_slice):
            logger.warning(
                "All recent events are dangling observations, which we truncate. This means the agent has only the essential first events. This should not happen.",
            )

        first_valid_event_index = slice_start_index + first_valid_event_index_in_slice

        if first_valid_event_index_in_slice > 0:
            logger.debug(
                "Removed %s dangling observation(s) from the start of recent event slice.",
                first_valid_event_index_in_slice,
            )

        return recent_events_slice, first_valid_event_index

    def _build_events_to_keep(
        self,
        events: list,
        essential_events: list[int],
        first_valid_event_index: int,
    ) -> set[int]:
        """Build the set of event IDs to keep.

        In addition to essential + recent events, file write/edit actions and
        their paired observations are preserved so the agent retains awareness
        of every file it has created or modified.
        """
        events_to_keep: set[int] = set(essential_events)

        for i in range(first_valid_event_index, len(events)):
            events_to_keep.add(events[i].id)

        # Importance-weighted: preserve file action events that would otherwise
        # be pruned, plus their paired observations.
        file_action_ids: set[int] = set()
        for ev in events:
            if ev.id not in events_to_keep and isinstance(
                ev, (FileEditAction, FileWriteAction)
            ):
                events_to_keep.add(ev.id)
                file_action_ids.add(ev.id)

        if file_action_ids:
            for ev in events:
                cause = getattr(ev, "cause", None)
                if (
                    cause is not None
                    and cause in file_action_ids
                    and isinstance(ev, Observation)
                ):
                    events_to_keep.add(ev.id)

        return events_to_keep

    def _create_condensation_action(
        self,
        pruned_event_ids: list[int],
    ) -> CondensationAction:
        """Create the appropriate CondensationAction based on pruned event IDs."""
        if not pruned_event_ids:
            return CondensationAction(pruned_event_ids=[])

        # Check if pruned events form a contiguous range.
        if (
            len(pruned_event_ids) > 1
            and pruned_event_ids[-1] - pruned_event_ids[0]
            == len(pruned_event_ids) - 1
        ):
            return CondensationAction(
                pruned_events_start_id=pruned_event_ids[0],
                pruned_events_end_id=pruned_event_ids[-1],
            )
        return CondensationAction(
            pruned_event_ids=pruned_event_ids,
        )

    def get_compaction(self, view: View) -> Compaction:
        """Apply conversation window truncation similar to _apply_conversation_window.

        This method:
        1. Identifies essential initial events (System Message, First User Message, Recall Observation)
        2. Keeps roughly half of the history
        3. Ensures action-observation pairs are preserved
        4. Returns a CondensationAction specifying which events to prune
        """
        events = view.events
        if not events:
            action = CondensationAction(pruned_event_ids=[])
            return Compaction(action=action)

        # Find essential events
        system_message, first_user_msg, recall_action, recall_observation = (
            self._find_essential_events(events)
        )

        if first_user_msg is None:
            logger.warning(
                "No first user message found in history during condensation."
            )
            action = CondensationAction(pruned_event_ids=[])
            return Compaction(action=action)

        # Build essential events list
        essential_events = self._build_essential_events_list(
            system_message,
            first_user_msg,
            recall_action,
            recall_observation,
        )

        # Calculate recent events to keep
        _recent_events_slice, first_valid_event_index = (
            self._calculate_recent_events_slice(events, essential_events)
        )

        # Build events to keep
        events_to_keep = self._build_events_to_keep(
            events, essential_events, first_valid_event_index
        )

        # Calculate pruned events.
        all_event_ids = {e.id for e in events}
        pruned_event_ids = sorted(all_event_ids - events_to_keep)

        logger.info(
                "ConversationWindowCompactor: Keeping %s events, pruning %s events.",
            len(events_to_keep),
            len(pruned_event_ids),
        )

        # Create condensation action
        action = self._create_condensation_action(pruned_event_ids)
        return Compaction(action=action)

    def _find_recall_and_observation(self, events, query, start_index):
        """Find recall action matching a query and its resulting observation.

        Args:
            events: List of all events to search through
            query: Query string to match in RecallAction
            start_index: Index to start searching from

        Returns:
            tuple: (recall_action, recall_observation) or (None, None) if not found

        Side Effects:
            None - Pure search function

        Notes:
            - Searches forward from start_index
            - Observation must have cause matching recall_action.id
            - Used to preserve query-response pairs in condensation

        Example:
            >>> recall_action, recall_obs = cond._find_recall_and_observation(
            ...     events, "find bug", 10
            ... )
            >>> recall_action.query
            'find bug'

        """
        recall_action = None
        recall_observation = None
        for i in range(start_index, len(events)):
            event = events[i]
            if isinstance(event, RecallAction) and event.query == query:
                recall_action = event
                for j in range(i + 1, len(events)):
                    obs_event = events[j]
                    if (
                        isinstance(obs_event, Observation)
                        and obs_event.cause == recall_action.id
                    ):
                        recall_observation = obs_event
                        break
                break
        return recall_action, recall_observation

    def should_compact(self, view: View) -> bool:
        """Condense proactively when event count exceeds threshold, or reactively on request."""
        if view.unhandled_condensation_request:
            return True
        # Proactive: condense before hitting the context window limit
        if len(view.events) > self._max_events:
            logger.info(
                "ConversationWindowCompactor: proactive compaction triggered "
                "(%d events > %d threshold)",
                len(view.events),
                self._max_events,
            )
            return True
        return False

    @classmethod
    def from_config(
        cls,
        _config: object,
        llm_registry: LLMRegistry,
    ) -> ConversationWindowCompactor:
        """Create a compactor instance from config."""
        return ConversationWindowCompactor(
            max_events=getattr(_config, "max_events", 100),
        )


# Lazy registration to avoid circular imports
def _register_config():
    """Register ConversationWindowCompactorConfig for the factory pattern.

    Args:
        None

    Returns:
        None

    Side Effects:
        - Registers ConversationWindowCompactorConfig with the compactor factory
        - Called at module load time

    Notes:
        - Deferred import avoids circular dependency on config module

    """
    from backend.core.config.compactor_config import ConversationWindowCompactorConfig

    ConversationWindowCompactor.register_config(ConversationWindowCompactorConfig)


_register_config()
