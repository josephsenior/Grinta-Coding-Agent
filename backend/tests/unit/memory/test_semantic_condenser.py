"""Tests for backend.memory.condenser.impl.semantic_condenser module.

Tests SemanticCondenser initialization, event scoring, selection, and
coherence logic without requiring LLM or external services.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, PropertyMock, patch

from backend.events.action import Action, MessageAction
from backend.events.action.agent import CondensationAction
from backend.events.observation import Observation
from backend.memory.condenser.condenser import Condensation
from backend.memory.condenser.impl.semantic_condenser import (
    EventImportance,
    SemanticCondenser,
)
from backend.memory.view import View


class _TestableCondenser(SemanticCondenser):
    """Concrete subclass that fills abstract method stubs for testing."""

    def should_condense(self, view):
        return len(view.events) > self.max_size if hasattr(view, "events") else False

    def condense(self, view):
        return self.get_condensation(view)


def _make_event(event_id: int, cls=None):
    if cls is None:
        from backend.events.event import Event
        cls = Event
    mock = MagicMock(spec=cls)
    mock.id = event_id
    mock.message = f"event-{event_id}"
    return mock


def _make_action(event_id: int, **attrs):
    mock = MagicMock(spec=Action)
    mock.id = event_id
    mock.message = f"action-{event_id}"
    for k, v in attrs.items():
        setattr(mock, k, v)
    return mock


def _make_observation(event_id: int, **attrs):
    mock = MagicMock(spec=Observation)
    mock.id = event_id
    mock.message = f"obs-{event_id}"
    for k, v in attrs.items():
        setattr(mock, k, v)
    return mock


def _make_message_action(event_id: int, **attrs):
    mock = MagicMock(spec=MessageAction)
    mock.id = event_id
    mock.message = f"msg-{event_id}"
    for k, v in attrs.items():
        setattr(mock, k, v)
    return mock


class TestSemanticCondenserInit(unittest.TestCase):
    def test_default_params(self):
        c = _TestableCondenser()
        self.assertEqual(c.keep_first, 5)
        self.assertEqual(c.max_size, 100)
        self.assertEqual(c.importance_threshold, 0.5)

    def test_custom_params(self):
        c = _TestableCondenser(keep_first=3, max_size=50, importance_threshold=0.8)
        self.assertEqual(c.keep_first, 3)
        self.assertEqual(c.max_size, 50)
        self.assertEqual(c.importance_threshold, 0.8)


class TestEventImportanceDataclass(unittest.TestCase):
    def test_creation(self):
        evt = _make_event(1)
        ei = EventImportance(event=evt, importance_score=0.7, reasons=["test"])
        self.assertIs(ei.event, evt)
        self.assertEqual(ei.importance_score, 0.7)
        self.assertEqual(ei.reasons, ["test"])


class TestSemanticCondenserScoring(unittest.TestCase):
    def setUp(self):
        self.condenser = _TestableCondenser(keep_first=2, max_size=10)

    def test_score_action_file_operation(self):
        action = _make_action(1, action="file_write")
        score, reasons = self.condenser._score_action_event(action)
        self.assertGreater(score, 0)
        self.assertIn("file_operation", reasons)

    def test_score_action_delegate(self):
        action = _make_action(2, action="delegate_task")
        score, reasons = self.condenser._score_action_event(action)
        self.assertGreater(score, 0)
        self.assertIn("delegation", reasons)

    def test_score_action_finish(self):
        action = _make_action(3, action="finish_task")
        score, reasons = self.condenser._score_action_event(action)
        self.assertGreater(score, 0)
        self.assertIn("completion", reasons)

    def test_score_action_setup_command(self):
        action = _make_action(4, command="npm install")
        score, reasons = self.condenser._score_action_event(action)
        self.assertGreater(score, 0)
        self.assertIn("setup_command", reasons)

    def test_score_action_no_special(self):
        action = MagicMock(spec=Action)
        action.id = 5
        del action.action
        del action.command
        score, reasons = self.condenser._score_action_event(action)
        self.assertEqual(score, 0.0)
        self.assertEqual(reasons, [])

    def test_score_observation_error(self):
        obs = _make_observation(10, error="something broke")
        score, reasons = self.condenser._score_observation_event(obs)
        self.assertGreater(score, 0)
        self.assertIn("error", reasons)

    def test_score_observation_success(self):
        obs = _make_observation(11, exit_code=0, error=None)
        score, reasons = self.condenser._score_observation_event(obs)
        self.assertGreater(score, 0)
        self.assertIn("success", reasons)

    def test_score_observation_detailed(self):
        obs = _make_observation(12, content="x" * 2000, error=None)
        score, reasons = self.condenser._score_observation_event(obs)
        self.assertGreater(score, 0)
        self.assertIn("detailed_output", reasons)

    def test_score_message_user(self):
        msg = _make_message_action(20, source="user")
        score, reasons = self.condenser._score_message_event(msg)
        self.assertGreater(score, 0)
        self.assertIn("user_message", reasons)

    def test_score_message_question(self):
        msg = _make_message_action(21, content="What is this?")
        score, reasons = self.condenser._score_message_event(msg)
        self.assertGreater(score, 0)
        self.assertIn("question", reasons)

    def test_calculate_importance_normalizes(self):
        action = _make_action(30, action="finish file delegate", command="build install")
        score, reasons = self.condenser._calculate_importance(action)
        self.assertLessEqual(score, 1.0)

    def test_calculate_importance_default_reason(self):
        evt = _make_event(40)
        score, reasons = self.condenser._calculate_importance(evt)
        self.assertIn("normal_importance", reasons)


class TestSemanticCondenserCondensation(unittest.TestCase):
    def test_no_condensation_under_max_size(self):
        c = _TestableCondenser(max_size=20)
        events = [_make_event(i) for i in range(10)]
        view = MagicMock(spec=View)
        view.events = events
        view.__len__ = lambda self: len(events)
        view.__iter__ = lambda self: iter(events)
        result = c.get_condensation(view)
        self.assertIsInstance(result, Condensation)
        self.assertEqual(result.action.forgotten_event_ids, [])

    def test_condensation_forgets_events(self):
        c = _TestableCondenser(keep_first=2, max_size=5, importance_threshold=0.9)
        events = [_make_event(i) for i in range(20)]
        view = MagicMock(spec=View)
        view.events = events
        view.__len__ = lambda self: len(events)
        view.__iter__ = lambda self: iter(events)
        result = c.get_condensation(view)
        self.assertIsInstance(result, Condensation)
        self.assertGreater(len(result.action.forgotten_event_ids), 0)

    def test_empty_events(self):
        c = _TestableCondenser()
        view = MagicMock(spec=View)
        view.events = []
        view.__len__ = lambda self: 0
        result = c.get_condensation(view)
        self.assertEqual(result.action.forgotten_event_ids, [])


class TestSemanticCondenserSelection(unittest.TestCase):
    def test_keeps_first_n(self):
        c = _TestableCondenser(keep_first=3, max_size=50)
        scored = [
            EventImportance(event=_make_event(i), importance_score=0.0, reasons=["low"])
            for i in range(10)
        ]
        keep = c._select_events_to_keep(scored)
        self.assertIn(0, keep)
        self.assertIn(1, keep)
        self.assertIn(2, keep)

    def test_keeps_recent_events(self):
        c = _TestableCondenser(keep_first=1, max_size=50)
        scored = [
            EventImportance(event=_make_event(i), importance_score=0.0, reasons=["low"])
            for i in range(50)
        ]
        keep = c._select_events_to_keep(scored)
        self.assertIn(49, keep)
        self.assertIn(45, keep)

    def test_keeps_high_importance(self):
        c = _TestableCondenser(keep_first=1, max_size=50, importance_threshold=0.5)
        scored = [
            EventImportance(event=_make_event(i), importance_score=0.1, reasons=["low"])
            for i in range(30)
        ]
        scored[15] = EventImportance(
            event=_make_event(15), importance_score=0.8, reasons=["important"]
        )
        keep = c._select_events_to_keep(scored)
        self.assertIn(15, keep)

    def test_trims_to_max_size(self):
        c = _TestableCondenser(keep_first=5, max_size=10, importance_threshold=0.0)
        scored = [
            EventImportance(event=_make_event(i), importance_score=0.5, reasons=["ok"])
            for i in range(50)
        ]
        keep = c._select_events_to_keep(scored)
        self.assertLessEqual(len(keep), 10)


class TestSemanticCondenserCoherence(unittest.TestCase):
    def test_keeps_observation_after_action(self):
        c = _TestableCondenser()
        action = _make_action(1)
        obs = _make_observation(2)
        events = [action, obs]
        keep_ids = {1}
        coherent = c._ensure_coherence(events, keep_ids)
        self.assertIn(2, coherent)

    def test_no_extra_for_non_action(self):
        c = _TestableCondenser()
        obs1 = _make_observation(1)
        obs2 = _make_observation(2)
        events = [obs1, obs2]
        keep_ids = {1}
        coherent = c._ensure_coherence(events, keep_ids)
        self.assertNotIn(2, coherent)


if __name__ == "__main__":
    unittest.main()
