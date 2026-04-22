"""Tests for attach_observation_cause."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.ledger.event import Event
from backend.ledger.observation import ErrorObservation
from backend.ledger.observation_cause import attach_observation_cause
from backend.ledger.tool import ToolCallMetadata


@pytest.fixture()
def obs() -> ErrorObservation:
    return ErrorObservation(content='x')


def test_attach_from_int(obs: ErrorObservation) -> None:
    attach_observation_cause(obs, 42)
    assert obs.cause == 42


def test_attach_from_action(obs: ErrorObservation) -> None:
    attach_observation_cause(obs, SimpleNamespace(id=7))
    assert obs.cause == 7


def test_attach_string_numeric_id(obs: ErrorObservation) -> None:
    attach_observation_cause(obs, SimpleNamespace(id='99'))
    assert obs.cause == 99


def test_attach_none_clears(obs: ErrorObservation) -> None:
    obs.cause = 1
    attach_observation_cause(obs, None)
    assert obs.cause is None


def test_invalid_id_clears(obs: ErrorObservation) -> None:
    attach_observation_cause(obs, Event.INVALID_ID)
    assert obs.cause is None


def test_copies_tool_call_metadata_from_action_when_missing(
    obs: ErrorObservation,
) -> None:
    meta = ToolCallMetadata(
        function_name='browser',
        tool_call_id='tc_1',
        model_response={'id': 'resp_1', 'choices': []},
        total_calls_in_response=1,
    )
    attach_observation_cause(obs, SimpleNamespace(id=7, tool_call_metadata=meta))
    assert obs.cause == 7
    assert obs.tool_call_metadata == meta


def test_preserves_existing_observation_tool_call_metadata(
    obs: ErrorObservation,
) -> None:
    src = ToolCallMetadata(
        function_name='browser',
        tool_call_id='tc_src',
        model_response={'id': 'resp_src', 'choices': []},
        total_calls_in_response=1,
    )
    existing = ToolCallMetadata(
        function_name='cmd',
        tool_call_id='tc_existing',
        model_response={'id': 'resp_existing', 'choices': []},
        total_calls_in_response=1,
    )
    obs.tool_call_metadata = existing
    attach_observation_cause(obs, SimpleNamespace(id=8, tool_call_metadata=src))
    assert obs.cause == 8
    assert obs.tool_call_metadata == existing
