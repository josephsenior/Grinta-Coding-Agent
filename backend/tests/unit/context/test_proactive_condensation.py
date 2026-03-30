"""Tests for proactive condensation threshold and file manifest preservation."""

from __future__ import annotations

import unittest
from typing import Any, cast
from unittest.mock import MagicMock

from backend.ledger.action.agent import CondensationAction
from backend.ledger.action.files import FileEditAction, FileWriteAction
from backend.ledger.action.message import MessageAction, SystemMessageAction
from backend.ledger.event import EventSource
from backend.ledger.observation import Observation
from backend.context.compactor.strategies.conversation_window_compactor import (
    ConversationWindowCompactor,
)
from backend.context.view import View


def _make_event(eid: int, cls=MessageAction, source=EventSource.AGENT, **kwargs):
    """Helper to create a mock event with a given id and class."""
    ev = MagicMock(spec=cls)
    ev.id = eid
    ev.source = source
    ev.content = kwargs.get("content", f"event-{eid}")
    # Make isinstance checks work
    ev.__class__ = cls
    return ev


def _make_view(events, unhandled=False):
    v = MagicMock(spec=View)
    v.events = events
    v.unhandled_condensation_request = unhandled
    return v


# ---------------------------------------------------------------------------
# Proactive condensation threshold
# ---------------------------------------------------------------------------
class TestProactiveCondensation(unittest.TestCase):
    """Verify should_compact triggers proactively based on event count."""

    def test_below_threshold_no_condense(self):
        condenser = ConversationWindowCompactor(max_events=100)
        events = [_make_event(i) for i in range(50)]
        view = _make_view(events, unhandled=False)
        self.assertFalse(condenser.should_compact(view))

    def test_at_threshold_no_condense(self):
        condenser = ConversationWindowCompactor(max_events=100)
        events = [_make_event(i) for i in range(100)]
        view = _make_view(events, unhandled=False)
        self.assertFalse(condenser.should_compact(view))

    def test_above_threshold_condenses(self):
        condenser = ConversationWindowCompactor(max_events=100)
        events = [_make_event(i) for i in range(101)]
        view = _make_view(events, unhandled=False)
        self.assertTrue(condenser.should_compact(view))

    def test_unhandled_request_always_condenses(self):
        condenser = ConversationWindowCompactor(max_events=100)
        events = [_make_event(i) for i in range(10)]
        view = _make_view(events, unhandled=True)
        self.assertTrue(condenser.should_compact(view))

    def test_custom_threshold(self):
        condenser = ConversationWindowCompactor(max_events=50)
        events = [_make_event(i) for i in range(51)]
        view = _make_view(events, unhandled=False)
        self.assertTrue(condenser.should_compact(view))

    def test_default_max_events_is_100(self):
        condenser = ConversationWindowCompactor()
        self.assertEqual(condenser._max_events, 100)


# ---------------------------------------------------------------------------
# File events preserved via importance-weighted condensation
# ---------------------------------------------------------------------------
class TestFileEventsPreserved(unittest.TestCase):
    """File events are now preserved directly (not via manifest summary)."""

    def _build_real_events(self, n_total: int, file_actions: dict[int, str] | None = None):
        """Build a realistic event list with system msg, user msg, and file actions."""
        events = []
        sys_msg = MagicMock(spec=SystemMessageAction)
        sys_msg.id = 0
        sys_msg.source = EventSource.USER
        sys_msg.__class__ = cast(Any, SystemMessageAction)
        events.append(sys_msg)

        user_msg = MagicMock(spec=MessageAction)
        user_msg.id = 1
        user_msg.source = EventSource.USER
        user_msg.content = "Create a Next.js app"
        user_msg.__class__ = cast(Any, MessageAction)
        events.append(user_msg)

        for i in range(2, n_total):
            if file_actions and i in file_actions:
                fa = MagicMock(spec=FileWriteAction)
                fa.id = i
                fa.source = EventSource.AGENT
                fa.path = file_actions[i]
                fa.__class__ = cast(Any, FileWriteAction)
                fa.content = f"content-{i}"
                fa.cause = None
                events.append(fa)
            else:
                ev = MagicMock(spec=MessageAction)
                ev.id = i
                ev.source = EventSource.AGENT
                ev.content = f"action-{i}"
                ev.__class__ = cast(Any, MessageAction)
                ev.cause = None
                events.append(ev)

        return events

    def test_file_events_not_pruned(self):
        """File action events are kept, so no manifest needed."""
        file_actions = {3: "src/app/page.tsx", 5: "src/app/layout.tsx"}
        events = self._build_real_events(20, file_actions)

        condenser = ConversationWindowCompactor(max_events=10)
        view = _make_view(events, unhandled=True)
        condensation = condenser.get_compaction(view)
        action = condensation.action

        pruned = set(action.pruned_event_ids or [])
        if action.pruned_events_start_id is not None and action.pruned_events_end_id is not None:
            pruned = set(range(
                action.pruned_events_start_id,
                action.pruned_events_end_id + 1,
            ))
        self.assertNotIn(3, pruned)
        self.assertNotIn(5, pruned)

    def test_no_summary_generated(self):
        """Summary/manifest is no longer generated (events preserved directly)."""
        file_actions = {3: "b.tsx", 4: "a.tsx"}
        events = self._build_real_events(20, file_actions)
        condenser = ConversationWindowCompactor(max_events=10)
        view = _make_view(events, unhandled=True)
        condensation = condenser.get_compaction(view)
        action = condensation.action
        self.assertIsNone(action.summary)
        self.assertIsNone(action.summary_offset)


# ---------------------------------------------------------------------------
# _create_condensation_action
# ---------------------------------------------------------------------------
class TestCreateCondensationAction(unittest.TestCase):
    """Verify _create_condensation_action builds correct actions."""

    def test_contiguous_range(self):
        condenser = ConversationWindowCompactor()
        action = condenser._create_condensation_action([2, 3, 4, 5])
        self.assertEqual(action.pruned_events_start_id, 2)
        self.assertEqual(action.pruned_events_end_id, 5)

    def test_non_contiguous_ids(self):
        condenser = ConversationWindowCompactor()
        action = condenser._create_condensation_action([2, 5, 8])
        self.assertEqual(action.pruned_event_ids, [2, 5, 8])

    def test_no_summary(self):
        condenser = ConversationWindowCompactor()
        action = condenser._create_condensation_action([2, 3, 4])
        self.assertIsNone(action.summary)

    def test_empty_pruned_ids(self):
        condenser = ConversationWindowCompactor()
        action = condenser._create_condensation_action([])
        self.assertEqual(action.pruned_event_ids, [])


# ---------------------------------------------------------------------------
# from_config
# ---------------------------------------------------------------------------
class TestFromConfig(unittest.TestCase):
    """Verify from_config passes max_events."""

    def test_from_config_passes_max_events(self):
        config = MagicMock()
        config.max_events = 200
        registry = MagicMock()
        condenser = ConversationWindowCompactor.from_config(config, registry)
        self.assertEqual(condenser._max_events, 200)

    def test_from_config_default_fallback(self):
        """If config doesn't have max_events, default to 100."""
        config = MagicMock(spec=[])  # spec=[] means no attributes
        registry = MagicMock()
        condenser = ConversationWindowCompactor.from_config(config, registry)
        self.assertEqual(condenser._max_events, 100)


if __name__ == "__main__":
    unittest.main()
