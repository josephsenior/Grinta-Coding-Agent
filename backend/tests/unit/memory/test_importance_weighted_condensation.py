"""Tests for importance-weighted condensation preserving file action events."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from backend.events.action.files import FileEditAction, FileWriteAction
from backend.events.action.message import MessageAction, SystemMessageAction
from backend.events.event import EventSource
from backend.events.observation import Observation
from backend.memory.condenser.strategies.conversation_window_condenser import (
    ConversationWindowCondenser,
)
from backend.memory.view import View


def _ev(eid, cls=MessageAction, source=EventSource.AGENT, **kwargs):
    """Create a mock event."""
    ev = MagicMock(spec=cls)
    ev.id = eid
    ev.source = source
    ev.content = kwargs.get("content", f"event-{eid}")
    ev.__class__ = cls  # type: ignore[assignment]
    # Default: no cause
    ev.cause = kwargs.get("cause", None)
    return ev


def _obs(eid, cause_id):
    """Create a mock Observation caused by a given action."""
    ob = MagicMock(spec=Observation)
    ob.id = eid
    ob.source = EventSource.ENVIRONMENT
    ob.content = f"obs-{eid}"
    ob.__class__ = Observation  # type: ignore[assignment]
    ob.cause = cause_id
    return ob


def _view(events, unhandled=False):
    v = MagicMock(spec=View)
    v.events = events
    v.unhandled_condensation_request = unhandled
    return v


class TestImportanceWeightedCondensation(unittest.TestCase):
    """Verify that FileWriteAction/FileEditAction events survive condensation."""

    def _build_events(self, n_total=30, file_indices=None, obs_for=None):
        """Build event list with system msg, user msg, file writes, and chat.

        file_indices: dict of index -> path for FileWriteAction events
        obs_for: dict of file_action_index -> obs_index for paired observations
        """
        file_indices = file_indices or {}
        obs_for = obs_for or {}
        events = []

        # 0: system message
        sys_msg = _ev(0, SystemMessageAction, EventSource.USER)
        events.append(sys_msg)

        # 1: first user message
        user_msg = _ev(1, MessageAction, EventSource.USER, content="Create app")
        events.append(user_msg)

        for i in range(2, n_total):
            if i in file_indices:
                fa = _ev(i, FileWriteAction, EventSource.AGENT)
                fa.path = file_indices[i]
                events.append(fa)
            elif i in obs_for.values():
                # Find the action this is an observation for
                action_id = next(k for k, v in obs_for.items() if v == i)
                events.append(_obs(i, action_id))
            else:
                events.append(_ev(i, MessageAction, EventSource.AGENT))

        return events

    def test_file_write_events_preserved(self):
        """FileWriteAction events in the forgotten region should be kept."""
        # Create 30 events with a file write at index 5 (early, would normally be forgotten)
        events = self._build_events(30, file_indices={5: "src/page.tsx"})

        condenser = ConversationWindowCondenser(max_events=20)
        view = _view(events, unhandled=True)
        condensation = condenser.get_condensation(view)
        action = condensation.action

        # Event 5 should NOT be forgotten
        forgotten = set(action.forgotten_event_ids or [])
        if action.forgotten_events_start_id is not None and action.forgotten_events_end_id is not None:
            forgotten = set(range(
                action.forgotten_events_start_id,
                action.forgotten_events_end_id + 1,
            ))
        self.assertNotIn(5, forgotten, "FileWriteAction at id=5 should be preserved")

    def test_file_edit_events_preserved(self):
        """FileEditAction events should also be preserved."""
        events = self._build_events(30)
        # Replace event at index 4 with a FileEditAction
        fa = _ev(4, FileEditAction, EventSource.AGENT)
        fa.path = "src/layout.tsx"
        events[4] = fa

        condenser = ConversationWindowCondenser(max_events=20)
        view = _view(events, unhandled=True)
        condensation = condenser.get_condensation(view)
        action = condensation.action

        forgotten = set(action.forgotten_event_ids or [])
        if action.forgotten_events_start_id is not None and action.forgotten_events_end_id is not None:
            forgotten = set(range(
                action.forgotten_events_start_id,
                action.forgotten_events_end_id + 1,
            ))
        self.assertNotIn(4, forgotten, "FileEditAction at id=4 should be preserved")

    def test_paired_observation_preserved(self):
        """Observation paired to a preserved file action should also be kept."""
        events = self._build_events(
            30,
            file_indices={5: "src/page.tsx"},
            obs_for={5: 6},
        )

        condenser = ConversationWindowCondenser(max_events=20)
        view = _view(events, unhandled=True)
        condensation = condenser.get_condensation(view)
        action = condensation.action

        forgotten = set(action.forgotten_event_ids or [])
        if action.forgotten_events_start_id is not None and action.forgotten_events_end_id is not None:
            forgotten = set(range(
                action.forgotten_events_start_id,
                action.forgotten_events_end_id + 1,
            ))
        self.assertNotIn(5, forgotten, "FileWriteAction should be preserved")
        self.assertNotIn(6, forgotten, "Paired observation should be preserved")

    def test_multiple_file_actions_preserved(self):
        """All file action events should be preserved, not just one."""
        file_indices = {3: "a.tsx", 5: "b.tsx", 7: "c.tsx", 9: "d.tsx"}
        events = self._build_events(30, file_indices=file_indices)

        condenser = ConversationWindowCondenser(max_events=20)
        view = _view(events, unhandled=True)
        condensation = condenser.get_condensation(view)
        action = condensation.action

        forgotten = set(action.forgotten_event_ids or [])
        if action.forgotten_events_start_id is not None and action.forgotten_events_end_id is not None:
            forgotten = set(range(
                action.forgotten_events_start_id,
                action.forgotten_events_end_id + 1,
            ))
        for eid in file_indices:
            self.assertNotIn(eid, forgotten, f"File action at id={eid} should be preserved")

    def test_non_file_events_still_forgotten(self):
        """Regular MessageAction events in the forgotten region should still be dropped."""
        events = self._build_events(30, file_indices={5: "page.tsx"})

        condenser = ConversationWindowCondenser(max_events=20)
        view = _view(events, unhandled=True)
        condensation = condenser.get_condensation(view)
        action = condensation.action

        forgotten = set(action.forgotten_event_ids or [])
        if action.forgotten_events_start_id is not None and action.forgotten_events_end_id is not None:
            forgotten = set(range(
                action.forgotten_events_start_id,
                action.forgotten_events_end_id + 1,
            ))
        # Some non-file, non-essential events should be forgotten
        non_essential_non_file = {e.id for e in events
                                  if e.id not in {0, 1, 5}
                                  and not isinstance(e, (FileWriteAction, FileEditAction))}
        self.assertTrue(
            forgotten & non_essential_non_file,
            "Some regular events should be forgotten",
        )

    def test_no_file_actions_no_change(self):
        """Without file actions, behavior is unchanged from before."""
        events = self._build_events(30)
        condenser = ConversationWindowCondenser(max_events=20)
        view = _view(events, unhandled=True)
        condensation = condenser.get_condensation(view)
        action = condensation.action

        forgotten = set(action.forgotten_event_ids or [])
        if action.forgotten_events_start_id is not None and action.forgotten_events_end_id is not None:
            forgotten = set(range(
                action.forgotten_events_start_id,
                action.forgotten_events_end_id + 1,
            ))
        # Some events should be forgotten (half the non-essential ones)
        self.assertTrue(len(forgotten) > 0, "Should forget some events")


if __name__ == "__main__":
    unittest.main()
