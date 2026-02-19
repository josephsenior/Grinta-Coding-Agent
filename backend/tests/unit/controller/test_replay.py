"""Unit tests for backend.controller.replay — Trajectory replay & determinism."""

from __future__ import annotations

import hashlib
from types import SimpleNamespace
from unittest.mock import MagicMock


from backend.controller.replay import ReplayDivergence, ReplayManager
from backend.events.action.action import Action
from backend.events.action.message import MessageAction
from backend.events.event import Event, EventSource
from backend.events.observation.empty import NullObservation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_action(source=EventSource.AGENT, content="do something"):
    """Build a minimal Action-compatible object."""
    a = MessageAction(content=content)
    a.source = source
    a.wait_for_response = False
    return a


def _make_observation(source=EventSource.ENVIRONMENT, content="done"):
    """Build a minimal observation-like event."""
    obs = SimpleNamespace(content=content, source=source)
    # The replay manager only checks isinstance(event, Action) and
    # isinstance(event, NullObservation); this is neither, so it's kept
    # as a normal event (observation).
    obs.__class__ = Event  # satisfy type checks loosely
    return obs


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


# ---------------------------------------------------------------------------
# ReplayDivergence dataclass
# ---------------------------------------------------------------------------


class TestReplayDivergence:
    def test_fields(self):
        d = ReplayDivergence(
            index=3,
            action_type="CmdRunAction",
            expected_hash="aaa",
            actual_hash="bbb",
            message="diverged",
        )
        assert d.index == 3
        assert d.action_type == "CmdRunAction"
        assert d.expected_hash == "aaa"
        assert d.actual_hash == "bbb"
        assert d.message == "diverged"


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestReplayManagerInit:
    def test_none_events(self):
        rm = ReplayManager(events=None)
        assert rm.replay_mode is False
        assert rm.replay_events == []
        assert rm.replay_index == 0

    def test_empty_events(self):
        rm = ReplayManager(events=[])
        assert rm.replay_mode is False
        assert rm.replay_events == []

    def test_events_with_actions(self):
        a1 = _make_action(source=EventSource.AGENT)
        a2 = _make_action(source=EventSource.AGENT, content="step 2")
        rm = ReplayManager(events=[a1, a2])
        assert rm.replay_mode is True
        assert len(rm.replay_events) == 2

    def test_environment_events_filtered(self):
        a1 = _make_action(source=EventSource.AGENT)
        env = _make_action(source=EventSource.ENVIRONMENT)
        rm = ReplayManager(events=[a1, env])
        # env-source events are skipped
        assert len(rm.replay_events) == 1

    def test_null_observations_filtered(self):
        a1 = _make_action(source=EventSource.AGENT)
        null_obs = NullObservation(content="")
        null_obs.source = EventSource.AGENT
        rm = ReplayManager(events=[a1, null_obs])
        assert len(rm.replay_events) == 1

    def test_wait_for_response_cleared(self):
        a1 = MessageAction(content="query")
        a1.source = EventSource.USER
        a1.wait_for_response = True
        a2 = _make_action(source=EventSource.AGENT)
        rm = ReplayManager(events=[a1, a2])
        # wait_for_response should be set to False
        assert rm.replay_events[0].wait_for_response is False


# ---------------------------------------------------------------------------
# should_replay / step
# ---------------------------------------------------------------------------


class TestShouldReplayAndStep:
    def test_should_replay_true_when_actions_available(self):
        a = _make_action()
        rm = ReplayManager(events=[a])
        assert rm.should_replay() is True

    def test_should_replay_false_when_empty(self):
        rm = ReplayManager(events=[])
        assert rm.should_replay() is False

    def test_should_replay_false_after_all_consumed(self):
        a = _make_action()
        rm = ReplayManager(events=[a])
        rm.step()  # consume only action
        assert rm.should_replay() is False

    def test_step_returns_action(self):
        a = _make_action(content="step 1")
        rm = ReplayManager(events=[a])
        result = rm.step()
        assert isinstance(result, Action)
        assert result.content == "step 1"

    def test_step_advances_index(self):
        a1 = _make_action(content="first")
        a2 = _make_action(content="second")
        rm = ReplayManager(events=[a1, a2])
        rm.step()
        assert rm.replay_index == 1
        rm.step()
        assert rm.replay_index == 2

    def test_should_replay_skips_non_actions(self):
        """Non-action events between actions should be skipped."""
        a1 = _make_action(content="first")
        obs = MagicMock(spec=Event)
        obs.source = EventSource.AGENT
        # Make isinstance(obs, Action) return False
        obs.__class__ = Event
        a2 = _make_action(content="second")
        rm = ReplayManager(events=[a1, obs, a2])
        rm.step()  # first action
        # should_replay will advance past the non-action obs to a2
        assert rm.should_replay() is True


# ---------------------------------------------------------------------------
# Determinism verification
# ---------------------------------------------------------------------------


class TestDeterminismVerification:
    def test_matching_observation_returns_true(self):
        a = _make_action()
        rm = ReplayManager(events=[a])
        rm.step()
        # With no expected observation, always true
        assert rm.verify_observation(None) is True

    def test_divergence_detected(self):
        a = _make_action()
        expected_obs = MagicMock()
        expected_obs.content = "expected output"
        expected_obs.source = EventSource.AGENT
        expected_obs.__class__ = Event

        rm = ReplayManager(events=[a, expected_obs])
        rm.step()  # advance past the action

        actual_obs = MagicMock()
        actual_obs.content = "different output"

        result = rm.verify_observation(actual_obs)
        assert result is False
        assert len(rm.divergences) == 1
        assert rm.is_deterministic is False

    def test_no_divergence_for_matching_content(self):
        a = _make_action()
        expected_obs = MagicMock()
        expected_obs.content = "same output"
        expected_obs.source = EventSource.AGENT
        expected_obs.__class__ = Event

        rm = ReplayManager(events=[a, expected_obs])
        rm.step()

        actual_obs = MagicMock()
        actual_obs.content = "same output"

        result = rm.verify_observation(actual_obs)
        assert result is True
        assert rm.is_deterministic is True

    def test_verification_disabled(self):
        a = _make_action()
        rm = ReplayManager(events=[a])
        rm._verify_determinism = False
        rm.step()
        # Always returns True when disabled
        assert rm.verify_observation(None) is True


# ---------------------------------------------------------------------------
# Content hashing
# ---------------------------------------------------------------------------


class TestContentHash:
    def test_none_event_hashes_to_none(self):
        h = ReplayManager._content_hash(None)
        assert h == "none"

    def test_event_with_content(self):
        ev = MagicMock()
        ev.content = "hello"
        h = ReplayManager._content_hash(ev)
        assert h == hashlib.sha256(b"hello").hexdigest()

    def test_event_without_content(self):
        ev = MagicMock(spec=[])  # no attributes
        h = ReplayManager._content_hash(ev)
        expected = hashlib.sha256(b"").hexdigest()
        assert h == expected

    def test_deterministic_hash(self):
        ev = MagicMock()
        ev.content = "test"
        h1 = ReplayManager._content_hash(ev)
        h2 = ReplayManager._content_hash(ev)
        assert h1 == h2


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


class TestSnapshot:
    def test_fields_present(self):
        a = _make_action()
        rm = ReplayManager(events=[a])
        snap = rm.snapshot()
        assert snap["replay_mode"] is True
        assert snap["replay_index"] == 0
        assert snap["total_events"] == 1
        assert snap["divergence_count"] == 0
        assert snap["is_deterministic"] is True

    def test_snapshot_reflects_state(self):
        a = _make_action()
        rm = ReplayManager(events=[a])
        rm.step()
        snap = rm.snapshot()
        assert snap["replay_index"] == 1

    def test_snapshot_empty_manager(self):
        rm = ReplayManager(events=None)
        snap = rm.snapshot()
        assert snap["replay_mode"] is False
        assert snap["total_events"] == 0


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


class TestProperties:
    def test_divergences_returns_copy(self):
        rm = ReplayManager(events=[_make_action()])
        divergences = rm.divergences
        assert divergences == []
        # Modifying the returned list should not affect internal state
        divergences.append("fake")
        assert not rm.divergences

    def test_is_deterministic_true_initially(self):
        rm = ReplayManager(events=[_make_action()])
        assert rm.is_deterministic is True
