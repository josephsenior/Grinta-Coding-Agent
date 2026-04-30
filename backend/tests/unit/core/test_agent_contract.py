"""Tests for backend.core.agent_contract."""

from __future__ import annotations

import pytest

from backend.core.agent_contract import build_agent_contract


def test_build_agent_contract_contains_expected_enum_groups() -> None:
    contract = build_agent_contract()
    enums = contract['enums']
    assert 'ActionType' in enums and 'AgentState' in enums
    assert isinstance(enums['ActionType'], dict)
    assert len(enums['ObservationType']) > 3


def test_build_agent_contract_action_type_values_are_strings() -> None:
    at = build_agent_contract()['enums']['ActionType']
    assert all(isinstance(v, str) for v in at.values())


@pytest.mark.parametrize(
    'group',
    (
        'ErrorSeverity',
        'ErrorCategory',
        'RuntimeStatus',
        'ActionConfirmationStatus',
    ),
)
def test_build_agent_contract_risk_and_error_enums_present(group: str) -> None:
    assert group in build_agent_contract()['enums']
