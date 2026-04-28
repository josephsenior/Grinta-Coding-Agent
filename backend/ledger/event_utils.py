"""Utility helpers for pairing actions and observations from event logs."""

from backend.core.logger import app_logger as logger
from backend.ledger.action.action import Action
from backend.ledger.action.empty import NullAction
from backend.ledger.event import Event
from backend.ledger.observation import (
    CmdOutputObservation,
    NullObservation,
    Observation,
)


def _build_action_and_observation_maps(
    events: list[Event],
) -> tuple[dict[int, Action], dict[int, Observation]]:
    """Build maps of actions and observations from events."""
    action_map: dict[int, Action] = {}
    observation_map: dict[int, Observation] = {}

    for event in events:
        if event.id is None or event.id == -1:
            logger.debug('Event %s has no ID', event)

        if isinstance(event, Action):
            action_map[event.id] = event

        if isinstance(event, Observation):
            if event.cause is None or event.cause == -1:
                logger.debug('Observation %s has no cause', event)
            if event.cause is not None:
                observation_map[event.cause] = event

    return action_map, observation_map


def _add_action_observation_pairs(
    tuples: list[tuple[Action, Observation]],
    action_map: dict[int, Action],
    observation_map: dict[int, Observation],
) -> None:
    """Add action-observation pairs to tuples list."""
    for action_id, action in action_map.items():
        if observation := observation_map.get(action_id):
            tuples.append((action, observation))
        else:
            tuples.append((action, NullObservation('')))


def _add_orphaned_observations(
    tuples: list[tuple[Action, Observation]],
    action_map: dict[int, Action],
    observation_map: dict[int, Observation],
) -> None:
    """Add observations that have no corresponding action."""
    for cause_id, observation in observation_map.items():
        if cause_id not in action_map:
            if isinstance(observation, NullObservation):
                continue
            if not isinstance(observation, CmdOutputObservation):
                logger.debug('Observation %s has no cause', observation)
            from backend.ledger.action.empty import NullActionReason
            tuples.append((NullAction(reason=NullActionReason.SENTINEL), observation))


def get_pairs_from_events(events: list[Event]) -> list[tuple[Action, Observation]]:
    """Return the history as a list of tuples (action, observation).

    Used by evals and visualization helpers that consume action/observation pairs.
    """
    tuples: list[tuple[Action, Observation]] = []
    action_map, observation_map = _build_action_and_observation_maps(events)
    _add_action_observation_pairs(tuples, action_map, observation_map)
    _add_orphaned_observations(tuples, action_map, observation_map)
    return tuples.copy()
