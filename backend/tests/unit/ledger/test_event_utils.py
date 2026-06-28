"""Unit tests for backend.ledger.event.event_utils — action/observation pairing."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from backend.ledger.action.action import Action
from backend.ledger.action.empty import NullAction
from backend.ledger.event.event_utils import (
    _add_action_observation_pairs,
    _add_orphaned_observations,
    _build_action_and_observation_maps,
    get_pairs_from_events,
)
from backend.ledger.observation import (
    CmdOutputObservation,
    NullObservation,
    Observation,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _action(event_id: int) -> Action:
    a = NullAction()
    a._id = event_id
    return a


def _obs(cause: int | None) -> Observation:
    o = NullObservation('')
    o._cause = cause
    return o


def _cmd_obs(cause: int | None, content: str = 'output') -> CmdOutputObservation:
    o = CmdOutputObservation(
        content=content,
        command_id=0,
        command='cmd',
        exit_code=0,
    )
    o._cause = cause
    return o


# ---------------------------------------------------------------------------
# _build_action_and_observation_maps
# ---------------------------------------------------------------------------


class TestBuildMaps:
    def test_empty(self):
        actions, observations = _build_action_and_observation_maps([])
        assert actions == {}
        assert observations == {}

    def test_actions_only(self):
        a1, a2 = _action(1), _action(2)
        actions, observations = _build_action_and_observation_maps([a1, a2])
        assert set(actions.keys()) == {1, 2}
        assert observations == {}

    def test_observations_only(self):
        o1, o2 = _obs(1), _obs(2)
        actions, observations = _build_action_and_observation_maps([o1, o2])
        assert actions == {}
        assert set(observations.keys()) == {1, 2}

    def test_mixed(self):
        a = _action(1)
        o = _obs(1)
        actions, observations = _build_action_and_observation_maps([a, o])
        assert 1 in actions
        assert 1 in observations

    def test_observation_without_cause_from_unit(self):
        obs = MagicMock(spec=NullObservation, id=10, cause=None)
        _, obs_map = _build_action_and_observation_maps([obs])
        assert not obs_map

    def test_event_without_id_from_unit(self):
        action = MagicMock(spec=NullAction, id=None)
        action_map, obs_map = _build_action_and_observation_maps([action])
        assert isinstance(action_map, dict)
        assert isinstance(obs_map, dict)

    def test_multiple_observations_same_cause_from_unit(self):
        obs1 = MagicMock(spec=NullObservation, id=10, cause=1)
        obs2 = MagicMock(spec=NullObservation, id=11, cause=1)
        _, obs_map = _build_action_and_observation_maps([obs1, obs2])
        assert obs_map[1] is obs2


# ---------------------------------------------------------------------------
# _add_action_observation_pairs
# ---------------------------------------------------------------------------


class TestAddPairs:
    def test_paired(self):
        a_map = {1: _action(1)}
        o_map = {1: _obs(1)}
        pairs: list = []
        _add_action_observation_pairs(pairs, a_map, o_map)
        assert len(pairs) == 1
        assert isinstance(pairs[0][0], Action)
        assert isinstance(pairs[0][1], Observation)

    def test_unpaired_action_gets_null_obs(self):
        a_map = {1: _action(1)}
        o_map: dict = {}
        pairs: list = []
        _add_action_observation_pairs(pairs, a_map, o_map)
        assert len(pairs) == 1
        assert isinstance(pairs[0][1], NullObservation)

    def test_multiple_pairs_from_unit(self):
        action1 = MagicMock(spec=NullAction, id=1)
        action2 = MagicMock(spec=NullAction, id=2)
        obs1 = MagicMock(spec=NullObservation, id=3, cause=1)
        obs2 = MagicMock(spec=NullObservation, id=4, cause=2)
        action_map: dict[int, Any] = {1: action1, 2: action2}
        obs_map: dict[int, Any] = {1: obs1, 2: obs2}
        pairs: list = []
        _add_action_observation_pairs(pairs, action_map, obs_map)
        assert len(pairs) == 2

    def test_empty_maps_from_unit(self):
        pairs: list = []
        _add_action_observation_pairs(pairs, {}, {})
        assert pairs == []


# ---------------------------------------------------------------------------
# _add_orphaned_observations
# ---------------------------------------------------------------------------


class TestOrphaned:
    def test_no_orphans(self):
        a_map = {1: _action(1)}
        o_map = {1: _obs(1)}
        pairs: list = []
        _add_orphaned_observations(pairs, a_map, o_map)
        assert not pairs  # 1 is in action_map

    def test_orphan_cmd_obs_added(self):
        a_map: dict[int, Any] = {}
        o_map: dict[int, Any] = {99: _cmd_obs(99)}
        pairs: list = []
        _add_orphaned_observations(pairs, a_map, o_map)
        assert len(pairs) == 1
        assert isinstance(pairs[0][0], NullAction)

    def test_null_obs_orphan_skipped(self):
        a_map: dict[int, Any] = {}
        o_map: dict[int, Any] = {99: NullObservation('')}
        # Set cause
        o_map[99]._cause = 99
        pairs: list = []
        _add_orphaned_observations(pairs, a_map, o_map)
        assert not pairs

    def test_observation_with_action_skipped_from_unit(self):
        action = MagicMock(spec=NullAction, id=1)
        obs = MagicMock(spec=CmdOutputObservation, id=2, cause=1)
        action_map: dict[int, Any] = {1: action}
        obs_map: dict[int, Any] = {1: obs}
        pairs: list = []
        _add_orphaned_observations(pairs, action_map, obs_map)
        assert not pairs

    def test_multiple_orphaned_from_unit(self):
        obs1 = MagicMock(spec=CmdOutputObservation, id=10, cause=99)
        obs2 = MagicMock(spec=CmdOutputObservation, id=11, cause=88)
        action_map: dict[int, Any] = {}
        obs_map: dict[int, Any] = {99: obs1, 88: obs2}
        pairs: list = []
        _add_orphaned_observations(pairs, action_map, obs_map)
        assert len(pairs) == 2


# ---------------------------------------------------------------------------
# get_pairs_from_events (integration)
# ---------------------------------------------------------------------------


class TestGetPairs:
    def test_empty(self):
        assert get_pairs_from_events([]) == []

    def test_paired_events(self):
        a = _action(1)
        o = _obs(1)
        pairs = get_pairs_from_events([a, o])
        assert len(pairs) == 1
        assert pairs[0] == (a, o)

    def test_returns_copy(self):
        a = _action(1)
        o = _obs(1)
        p1 = get_pairs_from_events([a, o])
        p2 = get_pairs_from_events([a, o])
        assert p1 is not p2

    def test_multiple_pairs(self):
        events = [_action(1), _obs(1), _action(2), _obs(2)]
        pairs = get_pairs_from_events(events)
        assert len(pairs) == 2

    def test_orphan_included(self):
        # Observation with cause=99 but no action 99
        o = _cmd_obs(99)
        pairs = get_pairs_from_events([o])
        assert len(pairs) == 1
        assert isinstance(pairs[0][0], NullAction)

    def test_action_without_observation_from_unit(self):
        action = MagicMock(spec=NullAction, id=1)
        pairs = get_pairs_from_events([action])
        assert len(pairs) == 1
        assert pairs[0][0] is action
        assert isinstance(pairs[0][1], NullObservation)

    def test_mixed_events_from_unit(self):
        action1 = MagicMock(spec=NullAction, id=1)
        obs1 = MagicMock(spec=NullObservation, id=2, cause=1)
        action2 = MagicMock(spec=NullAction, id=3)
        obs_orphan = MagicMock(spec=CmdOutputObservation, id=4, cause=99)
        pairs = get_pairs_from_events([action1, obs1, action2, obs_orphan])
        assert len(pairs) == 3
