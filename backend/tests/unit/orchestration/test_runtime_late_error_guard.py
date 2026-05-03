"""Tests for runtime_late_error_guard."""

from unittest.mock import MagicMock

import pytest

from backend.core.schemas import AgentState
from backend.orchestration.runtime_late_error_guard import (
    TERMINALS_NO_LATE_RUNTIME_ERROR_PROMOTION,
    should_skip_agent_error_transition_for_runtime_callback,
)


def test_terminals_frozenset_contains_stopped_and_finished() -> None:
    assert AgentState.STOPPED in TERMINALS_NO_LATE_RUNTIME_ERROR_PROMOTION
    assert AgentState.FINISHED in TERMINALS_NO_LATE_RUNTIME_ERROR_PROMOTION


@pytest.mark.parametrize(
    'state,expected',
    [
        (AgentState.STOPPED, True),
        (AgentState.FINISHED, True),
        (AgentState.RUNNING, False),
        (AgentState.RATE_LIMITED, False),
    ],
)
def test_should_skip_matches_terminal_policy(state, expected) -> None:
    ctrl = MagicMock()
    ctrl.get_agent_state = MagicMock(return_value=state)
    assert should_skip_agent_error_transition_for_runtime_callback(ctrl) is expected


def test_should_skip_false_when_get_agent_state_missing() -> None:
    ctrl = MagicMock(spec=['state'])
    del ctrl.get_agent_state
    assert should_skip_agent_error_transition_for_runtime_callback(ctrl) is False
