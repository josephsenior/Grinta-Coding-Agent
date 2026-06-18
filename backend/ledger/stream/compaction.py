"""Batch event compaction for the event history.

Unlike :class:`EventCoalescer` (which coalesces *live* streaming bursts),
``EventCompactor`` is a **post-hoc** pass that operates on an already-
collected event list — e.g. just before condensation — and removes or
merges redundant entries to reduce token waste.

Current compaction rules
~~~~~~~~~~~~~~~~~~~~~~~~
1. **Null removal** – drop consecutive ``NullAction`` / ``NullObservation``
   pairs that carry no semantic information.
2. **State-change folding** – collapse consecutive
   ``ChangeAgentStateAction`` / ``AgentStateChangedObservation`` pairs
   into a single pair representing the final state transition.
3. **Same-file edit folding** – when multiple ``FileEditAction`` events
   target the same path with no intervening non-edit events, keep only
   the last edit (it represents the final file state).

Usage::

    compactor = EventCompactor()
    compacted = compactor.compact(events)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.core.logger import app_logger as logger

if TYPE_CHECKING:
    from backend.ledger.event import Event


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _type_name(event: Event) -> str:
    return type(event).__name__


def _is_null(event: Event) -> bool:
    return _type_name(event) in {'NullAction', 'NullObservation'}


def _is_state_change(event: Event) -> bool:
    return _type_name(event) in {
        'ChangeAgentStateAction',
        'AgentStateChangedObservation',
    }


def _is_file_edit(event: Event) -> bool:
    return _type_name(event) == 'FileEditAction'


def _edit_path(event: Event) -> str | None:
    return getattr(event, 'path', None)


# ---------------------------------------------------------------------------
# Compactor
# ---------------------------------------------------------------------------


class EventCompactor:
    """Stateless batch compactor for event histories.

    Parameters:
        drop_nulls: Remove consecutive null events (default True).
        fold_state_changes: Collapse consecutive state transitions
            into the final one (default True).
        fold_file_edits: Keep only the last edit per file in a
            consecutive run of edits to the same path (default True).
    """

    def __init__(
        self,
        *,
        drop_nulls: bool = True,
        fold_state_changes: bool = True,
        fold_file_edits: bool = True,
    ) -> None:
        self.drop_nulls = drop_nulls
        self.fold_state_changes = fold_state_changes
        self.fold_file_edits = fold_file_edits

    def compact(self, events: list[Event]) -> list[Event]:
        """Return a new list with redundant events removed or merged.

        The original list is **not** mutated.
        """
        if not events:
            return []

        result = list(events)
        original_len = len(result)

        if self.drop_nulls:
            result = self._drop_nulls(result)
        if self.fold_state_changes:
            result = self._fold_state_changes(result)
        if self.fold_file_edits:
            result = self._fold_file_edits(result)

        removed = original_len - len(result)
        if removed > 0:
            logger.debug('EventCompactor: removed %d/%d events', removed, original_len)
        return result

    # ------------------------------------------------------------------ #
    # Rule implementations
    # ------------------------------------------------------------------ #

    @staticmethod
    def _drop_nulls(events: list[Event]) -> list[Event]:
        """Remove NullAction / NullObservation events."""
        return [e for e in events if not _is_null(e)]

    @staticmethod
    def _fold_state_changes(events: list[Event]) -> list[Event]:
        """Collapse consecutive state-change pairs to the last pair."""
        if not events:
            return events

        result: list[Event] = []
        i = 0
        while i < len(events):
            if not _is_state_change(events[i]):
                result.append(events[i])
                i += 1
                continue

            # Consume the full run of consecutive state-change events
            run_start = i
            while i < len(events) and _is_state_change(events[i]):
                i += 1

            # Keep only the last two (action + observation pair) or last one
            run = events[run_start:i]
            if len(run) >= 2:
                result.extend(run[-2:])
            else:
                result.extend(run)

        return result

    @staticmethod
    def _fold_file_edits(events: list[Event]) -> list[Event]:
        """In consecutive same-path edit runs, keep only the final edit."""
        if not events:
            return events

        result: list[Event] = []
        i = 0
        while i < len(events):
            if not _is_file_edit(events[i]):
                result.append(events[i])
                i += 1
                continue

            # Consume run of edits to the same path
            current_path = _edit_path(events[i])
            while (
                i < len(events)
                and _is_file_edit(events[i])
                and _edit_path(events[i]) == current_path
            ):
                i += 1

            # Keep only the last edit in the run
            result.append(events[i - 1])

        return result
