"""Tests for attach_observation_cause."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.events.event import Event
from backend.events.observation import ErrorObservation
from backend.events.observation_cause import attach_observation_cause


@pytest.fixture()
def obs() -> ErrorObservation:
    return ErrorObservation(content="x")


def test_attach_from_int(obs: ErrorObservation) -> None:
    attach_observation_cause(obs, 42)
    assert obs.cause == 42


def test_attach_from_action(obs: ErrorObservation) -> None:
    attach_observation_cause(obs, SimpleNamespace(id=7))
    assert obs.cause == 7


def test_attach_string_numeric_id(obs: ErrorObservation) -> None:
    attach_observation_cause(obs, SimpleNamespace(id="99"))
    assert obs.cause == 99


def test_attach_none_clears(obs: ErrorObservation) -> None:
    obs.cause = 1
    attach_observation_cause(obs, None)
    assert obs.cause is None


def test_invalid_id_clears(obs: ErrorObservation) -> None:
    attach_observation_cause(obs, Event.INVALID_ID)
    assert obs.cause is None
