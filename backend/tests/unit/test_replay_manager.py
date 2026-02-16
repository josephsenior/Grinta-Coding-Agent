"""Tests for backend.controller.replay module — ReplayManager and ReplayDivergence."""

import hashlib
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.controller.replay import ReplayDivergence, ReplayManager
from backend.events.action.message import MessageAction
from backend.events.event import EventSource
from backend.events.observation.empty import NullObservation


def _make_action(source=EventSource.USER, content="test"):
    a = MessageAction(content=content)
    a.source = source
    return a


def _make_observation(source=EventSource.ENVIRONMENT, content="obs"):
    o = NullObservation(content=content)
    o.source = source
    return o


class TestReplayDivergence:
    def test_fields(self):
        d = ReplayDivergence(
            index=5,
            action_type="MessageAction",
            expected_hash="abc123",
            actual_hash="def456",
            message="Diverged at 5",
        )
        assert d.index == 5
        assert d.action_type == "MessageAction"
        assert d.expected_hash == "abc123"
        assert d.actual_hash == "def456"
        assert d.message == "Diverged at 5"


class TestReplayManagerInit:
    def test_empty_events(self):
        rm = ReplayManager(None)
        assert rm.replay_mode is False
        assert rm.replay_index == 0
        assert rm.replay_events == []

    def test_empty_list(self):
        rm = ReplayManager([])
        assert rm.replay_mode is False

    def test_filters_environment_events(self):
        env_obs = _make_observation(source=EventSource.ENVIRONMENT)
        user_action = _make_action(source=EventSource.USER)
        rm = ReplayManager([env_obs, user_action])
        assert len(rm.replay_events) == 1
        assert rm.replay_mode is True

    def test_filters_null_observations(self):
        null_obs = NullObservation(content="")
        null_obs.source = EventSource.USER
        action = _make_action()
        rm = ReplayManager([null_obs, action])
        # NullObservation should be filtered out
        assert len(rm.replay_events) == 1

    def test_disables_wait_for_response(self):
        a1 = _make_action(content="msg1")
        a1.wait_for_response = True
        a2 = _make_action(content="msg2")
        rm = ReplayManager([a1, a2])
        # First action's wait_for_response should be set to False
        assert rm.replay_events[0].wait_for_response is False


class TestShouldReplay:
    def test_no_replay_mode(self):
        rm = ReplayManager(None)
        assert rm.should_replay() is False

    def test_replay_with_actions(self):
        action = _make_action()
        rm = ReplayManager([action])
        assert rm.should_replay() is True

    def test_replay_finished(self):
        action = _make_action()
        rm = ReplayManager([action])
        rm.replay_index = 1  # past the end
        assert rm.should_replay() is False


class TestStep:
    def test_returns_action(self):
        action = _make_action(content="first")
        rm = ReplayManager([action])
        result = rm.step()
        assert result.content == "first"
        assert rm.replay_index == 1

    def test_multiple_steps(self):
        a1 = _make_action(content="first")
        a2 = _make_action(content="second")
        rm = ReplayManager([a1, a2])
        assert rm.step().content == "first"
        assert rm.step().content == "second"
        assert rm.replay_index == 2


class TestVerifyObservation:
    def test_matching_observations(self):
        action = _make_action()
        rm = ReplayManager([action])
        rm.step()  # advance past the action
        # No expected observation after the action
        result = rm.verify_observation(None)
        assert result is True

    def test_disabled_verification(self):
        action = _make_action()
        rm = ReplayManager([action])
        rm._verify_determinism = False
        rm.step()
        result = rm.verify_observation(MagicMock(content="different"))
        assert result is True

    def test_no_events(self):
        rm = ReplayManager(None)
        result = rm.verify_observation(None)
        assert result is True


class TestDivergences:
    def test_initially_deterministic(self):
        rm = ReplayManager(None)
        assert rm.is_deterministic is True
        assert rm.divergences == []

    def test_divergence_tracked(self):
        rm = ReplayManager(None)
        rm._divergences.append(
            ReplayDivergence(
                index=0,
                action_type="Test",
                expected_hash="a",
                actual_hash="b",
                message="diverged",
            )
        )
        assert rm.is_deterministic is False
        assert len(rm.divergences) == 1


class TestSnapshot:
    def test_initial_snapshot(self):
        rm = ReplayManager(None)
        snap = rm.snapshot()
        assert snap["replay_mode"] is False
        assert snap["replay_index"] == 0
        assert snap["total_events"] == 0
        assert snap["divergence_count"] == 0
        assert snap["is_deterministic"] is True

    def test_active_replay_snapshot(self):
        action = _make_action()
        rm = ReplayManager([action])
        snap = rm.snapshot()
        assert snap["replay_mode"] is True
        assert snap["total_events"] == 1


class TestContentHash:
    def test_none_event(self):
        assert ReplayManager._content_hash(None) == "none"

    def test_event_with_content(self):
        event = SimpleNamespace(content="hello")
        h = ReplayManager._content_hash(event)
        expected = hashlib.sha256(b"hello").hexdigest()
        assert h == expected

    def test_event_with_none_content(self):
        event = SimpleNamespace(content=None)
        h = ReplayManager._content_hash(event)
        expected = hashlib.sha256(b"").hexdigest()
        assert h == expected

    def test_event_without_content_attr(self):
        event = SimpleNamespace()
        h = ReplayManager._content_hash(event)
        expected = hashlib.sha256(b"").hexdigest()
        assert h == expected
