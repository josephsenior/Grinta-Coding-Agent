"""Tests for backend.events.event_utils — action/observation pair extraction."""

from typing import Any

from backend.events.action.empty import NullAction
from backend.events.action.message import MessageAction
from backend.events.observation import CmdOutputObservation, NullObservation
from backend.events.event_utils import (
    _add_action_observation_pairs,
    _add_orphaned_observations,
    _build_action_and_observation_maps,
    get_pairs_from_events,
)


def _make_message(id_: int, content: str = "msg") -> MessageAction:
    m = MessageAction(content=content)
    m._id = id_
    return m


def _make_cmd_obs(
    cause_: int, content: str = "ok", exit_code: int = 0
) -> CmdOutputObservation:
    obs = CmdOutputObservation(
        content=content, command_id=0, command="echo", exit_code=exit_code
    )
    obs._cause = cause_
    return obs


def _make_null_obs(cause_: int) -> NullObservation:
    obs = NullObservation(content="")
    obs._cause = cause_
    return obs


# ── _build_action_and_observation_maps ────────────────────────────────


class TestBuildMaps:
    def test_empty_events(self):
        actions, observations = _build_action_and_observation_maps([])
        assert actions == {}
        assert observations == {}

    def test_actions_only(self):
        m1 = _make_message(1)
        m2 = _make_message(2)
        actions, observations = _build_action_and_observation_maps([m1, m2])
        assert 1 in actions
        assert 2 in actions
        assert observations == {}

    def test_observations_mapped_by_cause(self):
        m = _make_message(1)
        obs = _make_cmd_obs(1)
        actions, observations = _build_action_and_observation_maps([m, obs])
        assert 1 in actions
        assert 1 in observations
        assert observations[1] is obs


# ── _add_action_observation_pairs ─────────────────────────────────────


class TestAddPairs:
    def test_paired(self):
        action_map: dict[int, Any] = {1: _make_message(1)}
        obs_map: dict[int, Any] = {1: _make_cmd_obs(1)}
        tuples: list[Any] = []
        _add_action_observation_pairs(tuples, action_map, obs_map)
        assert len(tuples) == 1
        assert tuples[0][0] is action_map[1]
        assert tuples[0][1] is obs_map[1]

    def test_unpaired_action_gets_null_obs(self):
        action_map: dict[int, Any] = {1: _make_message(1)}
        obs_map: dict[int, Any] = {}
        tuples: list[Any] = []
        _add_action_observation_pairs(tuples, action_map, obs_map)
        assert len(tuples) == 1
        assert isinstance(tuples[0][1], NullObservation)


# ── _add_orphaned_observations ────────────────────────────────────────


class TestOrphanedObservations:
    def test_orphaned_cmd_output(self):
        action_map: dict[int, Any] = {}
        obs = _make_cmd_obs(99)
        obs_map: dict[int, Any] = {99: obs}
        tuples: list[Any] = []
        _add_orphaned_observations(tuples, action_map, obs_map)
        assert len(tuples) == 1
        assert isinstance(tuples[0][0], NullAction)
        assert tuples[0][1] is obs

    def test_null_observation_skipped(self):
        action_map: dict[int, Any] = {}
        obs = _make_null_obs(99)
        obs_map: dict[int, Any] = {99: obs}
        tuples: list[Any] = []
        _add_orphaned_observations(tuples, action_map, obs_map)
        assert not tuples

    def test_already_paired_not_orphaned(self):
        action = _make_message(1)
        obs = _make_cmd_obs(1)
        action_map: dict[int, Any] = {1: action}
        obs_map: dict[int, Any] = {1: obs}
        tuples: list[Any] = []
        _add_orphaned_observations(tuples, action_map, obs_map)
        assert not tuples  # cause=1 is in action_map


# ── get_pairs_from_events ─────────────────────────────────────────────


class TestGetPairsFromEvents:
    def test_empty(self):
        assert get_pairs_from_events([]) == []

    def test_single_paired(self):
        m = _make_message(1)
        obs = _make_cmd_obs(1)
        pairs = get_pairs_from_events([m, obs])
        assert len(pairs) == 1
        assert pairs[0][0] is m
        assert pairs[0][1] is obs

    def test_multiple_pairs(self):
        m1 = _make_message(1)
        m2 = _make_message(2)
        o1 = _make_cmd_obs(1)
        o2 = _make_cmd_obs(2)
        pairs = get_pairs_from_events([m1, m2, o1, o2])
        assert len(pairs) == 2

    def test_action_without_observation(self):
        m = _make_message(1)
        pairs = get_pairs_from_events([m])
        assert len(pairs) == 1
        assert isinstance(pairs[0][1], NullObservation)

    def test_returns_copy(self):
        """get_pairs_from_events should return a copy of the internal list."""
        m = _make_message(1)
        pairs1 = get_pairs_from_events([m])
        pairs2 = get_pairs_from_events([m])
        assert pairs1 is not pairs2
