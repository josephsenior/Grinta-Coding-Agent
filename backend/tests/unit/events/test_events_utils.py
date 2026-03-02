"""Tests for backend.events.utils — action/observation pairing utilities."""

from typing import Any
from unittest.mock import MagicMock


from backend.events.utils import (
    _build_action_and_observation_maps,
    _add_action_observation_pairs,
    _add_orphaned_observations,
    get_pairs_from_events,
)
from backend.events.action.empty import NullAction
from backend.events.observation import NullObservation, CmdOutputObservation


class TestBuildActionAndObservationMaps:
    """Tests for_build_action_and_observation_maps function."""

    def test_empty_events(self):
        """Test with empty event list."""
        action_map, obs_map = _build_action_and_observation_maps([])
        assert action_map == {}
        assert obs_map == {}

    def test_action_only(self):
        """Test with action events only."""
        action1 = MagicMock(spec=NullAction, id=1)
        action2 = MagicMock(spec=NullAction, id=2)

        action_map, obs_map = _build_action_and_observation_maps([action1, action2])

        assert len(action_map) == 2
        assert action_map[1] is action1
        assert action_map[2] is action2
        assert obs_map == {}

    def test_observation_only(self):
        """Test with observation events only."""
        obs1 = MagicMock(spec=NullObservation, id=10, cause=1)
        obs2 = MagicMock(spec=NullObservation, id=11, cause=2)

        action_map, obs_map = _build_action_and_observation_maps([obs1, obs2])

        assert action_map == {}
        assert len(obs_map) == 2
        assert obs_map[1] is obs1  # Keyed by cause
        assert obs_map[2] is obs2

    def test_action_and_observation(self):
        """Test with both actions and observations."""
        action = MagicMock(spec=NullAction, id=5)
        obs = MagicMock(spec=NullObservation, id=6, cause=5)

        action_map, obs_map = _build_action_and_observation_maps([action, obs])

        assert action_map[5] is action
        assert obs_map[5] is obs

    def test_observation_without_cause(self):
        """Test observation with no cause is skipped."""
        obs = MagicMock(spec=NullObservation, id=10, cause=None)

        action_map, obs_map = _build_action_and_observation_maps([obs])

        assert not obs_map

    def test_event_without_id(self):
        """Test event with no ID."""
        action = MagicMock(spec=NullAction, id=None)

        action_map, obs_map = _build_action_and_observation_maps([action])

        # Should skip or handle gracefully
        assert isinstance(action_map, dict)
        assert isinstance(obs_map, dict)

    def test_multiple_observations_same_cause(self):
        """Test last observation wins for same cause."""
        obs1 = MagicMock(spec=NullObservation, id=10, cause=1)
        obs2 = MagicMock(spec=NullObservation, id=11, cause=1)

        action_map, obs_map = _build_action_and_observation_maps([obs1, obs2])

        # Last one should overwrite
        assert obs_map[1] is obs2


class TestAddActionObservationPairs:
    """Tests for _add_action_observation_pairs function."""

    def test_matched_pairs(self):
        """Test adding matched action-observation pairs."""
        action = MagicMock(spec=NullAction, id=1)
        obs = MagicMock(spec=NullObservation, id=2, cause=1)

        action_map: dict[int, Any] = {1: action}
        obs_map: dict[int, Any] = {1: obs}
        tuples: list[Any] = []

        _add_action_observation_pairs(tuples, action_map, obs_map)

        assert len(tuples) == 1
        assert tuples[0] == (action, obs)

    def test_action_without_observation(self):
        """Test action without matching observation gets NullObservation."""
        action = MagicMock(spec=NullAction, id=1)

        action_map: dict[int, Any] = {1: action}
        obs_map: dict[int, Any] = {}
        tuples: list[Any] = []

        _add_action_observation_pairs(tuples, action_map, obs_map)

        assert len(tuples) == 1
        assert tuples[0][0] is action
        assert isinstance(tuples[0][1], NullObservation)

    def test_multiple_pairs(self):
        """Test multiple action-observation pairs."""
        action1 = MagicMock(spec=NullAction, id=1)
        action2 = MagicMock(spec=NullAction, id=2)
        obs1 = MagicMock(spec=NullObservation, id=3, cause=1)
        obs2 = MagicMock(spec=NullObservation, id=4, cause=2)

        action_map: dict[int, Any] = {1: action1, 2: action2}
        obs_map: dict[int, Any] = {1: obs1, 2: obs2}
        tuples: list[Any] = []

        _add_action_observation_pairs(tuples, action_map, obs_map)

        assert len(tuples) == 2

    def test_empty_maps(self):
        """Test with empty maps."""
        tuples: list[Any] = []
        _add_action_observation_pairs(tuples, {}, {})
        assert tuples == []


class TestAddOrphanedObservations:
    """Tests for _add_orphaned_observations function."""

    def test_orphaned_observation(self):
        """Test observation without matching action."""
        obs = MagicMock(spec=CmdOutputObservation, id=10, cause=99)

        action_map: dict[int, Any] = {}
        obs_map: dict[int, Any] = {99: obs}
        tuples: list[Any] = []

        _add_orphaned_observations(tuples, action_map, obs_map)

        assert len(tuples) == 1
        assert isinstance(tuples[0][0], NullAction)
        assert tuples[0][1] is obs

    def test_null_observation_skipped(self):
        """Test NullObservation without action is skipped."""
        obs = MagicMock(spec=NullObservation, id=10, cause=99)

        action_map: dict[int, Any] = {}
        obs_map: dict[int, Any] = {99: obs}
        tuples: list[Any] = []

        _add_orphaned_observations(tuples, action_map, obs_map)

        assert not tuples

    def test_observation_with_action_skipped(self):
        """Test observation with matching action is not added."""
        action = MagicMock(spec=NullAction, id=1)
        obs = MagicMock(spec=CmdOutputObservation, id=2, cause=1)

        action_map: dict[int, Any] = {1: action}
        obs_map: dict[int, Any] = {1: obs}
        tuples: list[Any] = []

        _add_orphaned_observations(tuples, action_map, obs_map)

        # Should not add since action exists
        assert not tuples

    def test_multiple_orphaned(self):
        """Test multiple orphaned observations."""
        obs1 = MagicMock(spec=CmdOutputObservation, id=10, cause=99)
        obs2 = MagicMock(spec=CmdOutputObservation, id=11, cause=88)

        action_map: dict[int, Any] = {}
        obs_map: dict[int, Any] = {99: obs1, 88: obs2}
        tuples: list[Any] = []

        _add_orphaned_observations(tuples, action_map, obs_map)

        assert len(tuples) == 2


class TestGetPairsFromEvents:
    """Tests for get_pairs_from_events function."""

    def test_empty_events(self):
        """Test with empty event list."""
        pairs = get_pairs_from_events([])
        assert pairs == []

    def test_single_action_observation_pair(self):
        """Test single matched pair."""
        action = MagicMock(spec=NullAction, id=1)
        obs = MagicMock(spec=NullObservation, id=2, cause=1)

        pairs = get_pairs_from_events([action, obs])

        assert len(pairs) == 1
        assert pairs[0] == (action, obs)

    def test_action_without_observation(self):
        """Test action without observation."""
        action = MagicMock(spec=NullAction, id=1)

        pairs = get_pairs_from_events([action])

        assert len(pairs) == 1
        assert pairs[0][0] is action
        assert isinstance(pairs[0][1], NullObservation)

    def test_orphaned_observation(self):
        """Test observation without action."""
        obs = MagicMock(spec=CmdOutputObservation, id=10, cause=99)

        pairs = get_pairs_from_events([obs])

        assert len(pairs) == 1
        assert isinstance(pairs[0][0], NullAction)
        assert pairs[0][1] is obs

    def test_mixed_events(self):
        """Test mixed matched, unmatched actions and observations."""
        action1 = MagicMock(spec=NullAction, id=1)
        obs1 = MagicMock(spec=NullObservation, id=2, cause=1)
        action2 = MagicMock(spec=NullAction, id=3)  # No observation
        obs_orphan = MagicMock(spec=CmdOutputObservation, id=4, cause=99)

        pairs = get_pairs_from_events([action1, obs1, action2, obs_orphan])

        assert len(pairs) == 3
        # Should have (action1, obs1), (action2, NullObs), (NullAction, obs_orphan)

    def test_returns_copy(self):
        """Test returned list is a copy."""
        action = MagicMock(spec=NullAction, id=1)
        pairs1 = get_pairs_from_events([action])
        pairs2 = get_pairs_from_events([action])

        # Should be different list objects
        assert pairs1 is not pairs2
