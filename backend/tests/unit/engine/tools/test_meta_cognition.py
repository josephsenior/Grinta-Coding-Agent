"""Unit tests for the unified communicate_with_user tool handler."""

from __future__ import annotations

import pytest

from backend.core.errors import FunctionCallValidationError
from backend.engine.tools._tool_handlers import _handle_communicate_tool
from backend.ledger.action.agent import (
    ClarificationRequestAction,
    ConfirmRequestAction,
    EscalateToHumanAction,
    InformAction,
    ProposalAction,
    UncertaintyAction,
)


def test_clarification_with_plain_string_options() -> None:
    action = _handle_communicate_tool(
        {
            'intent': 'clarification',
            'message': 'Which one?',
            'options': ['A', 'B'],
        }
    )
    assert isinstance(action, ClarificationRequestAction)
    assert action.question == 'Which one?'
    assert action.options == ['A', 'B']


def test_clarification_with_structured_options() -> None:
    action = _handle_communicate_tool(
        {
            'intent': 'clarification',
            'message': 'Pick a lib?',
            'options': [
                {'label': 'requests', 'description': 'simple'},
                {'label': 'httpx', 'description': 'async'},
            ],
        }
    )
    assert isinstance(action, ClarificationRequestAction)
    # Plain labels are extracted for the simple field.
    assert action.options == ['requests', 'httpx']


def test_proposal_threads_recommended() -> None:
    action = _handle_communicate_tool(
        {
            'intent': 'proposal',
            'message': 'Pick an approach',
            'options': [
                {'label': 'A', 'description': 'fast'},
                {'label': 'B', 'description': 'safe'},
                {'label': 'C', 'description': 'cheap'},
            ],
            'recommended': 2,
        }
    )
    assert isinstance(action, ProposalAction)
    assert action.recommended == 2
    assert action.options[0]['approach'] == 'A'
    assert action.options[2]['approach'] == 'C'


def test_proposal_clamps_out_of_range_recommended() -> None:
    action = _handle_communicate_tool(
        {
            'intent': 'proposal',
            'message': 'Pick',
            'options': [{'label': 'A'}, {'label': 'B'}],
            'recommended': 99,
        }
    )
    assert isinstance(action, ProposalAction)
    # Clamped to the last valid index.
    assert action.recommended == 1


def test_uncertainty_threads_level() -> None:
    action = _handle_communicate_tool(
        {
            'intent': 'uncertainty',
            'message': 'wrong path',
            'uncertainty_level': 0.2,
        }
    )
    assert isinstance(action, UncertaintyAction)
    assert action.uncertainty_level == 0.2


def test_uncertainty_clamps_level_to_unit_interval() -> None:
    too_high = _handle_communicate_tool(
        {
            'intent': 'uncertainty',
            'message': 'x',
            'uncertainty_level': 5.0,
        }
    )
    assert isinstance(too_high, UncertaintyAction)
    assert too_high.uncertainty_level == 1.0

    too_low = _handle_communicate_tool(
        {
            'intent': 'uncertainty',
            'message': 'x',
            'uncertainty_level': -0.5,
        }
    )
    assert isinstance(too_low, UncertaintyAction)
    assert too_low.uncertainty_level == 0.0


def test_uncertainty_defaults_to_half_when_missing() -> None:
    action = _handle_communicate_tool({'intent': 'uncertainty', 'message': 'x'})
    assert isinstance(action, UncertaintyAction)
    assert action.uncertainty_level == 0.5


def test_confirm_uses_default_options_when_missing() -> None:
    action = _handle_communicate_tool(
        {'intent': 'confirm', 'message': 'Delete the table?'}
    )
    assert isinstance(action, ConfirmRequestAction)
    assert action.options == ['Yes, do it', 'No, abort']
    # default_index defaults to 1 (safe: deny).
    assert action.default_index == 1


def test_confirm_respects_explicit_default_index() -> None:
    action = _handle_communicate_tool(
        {
            'intent': 'confirm',
            'message': 'Push to main?',
            'options': ['Yes, push', 'No, stop'],
            'default_index': 0,
        }
    )
    assert isinstance(action, ConfirmRequestAction)
    assert action.default_index == 0


def test_confirm_clamps_default_index_to_safe_set() -> None:
    """default_index must be 0 or 1; anything else is normalized to 1."""
    action = _handle_communicate_tool(
        {
            'intent': 'confirm',
            'message': 'x',
            'default_index': 7,
        }
    )
    assert isinstance(action, ConfirmRequestAction)
    assert action.default_index == 1


def test_inform_does_not_have_options() -> None:
    action = _handle_communicate_tool(
        {'intent': 'inform', 'message': 'Created 2 helper files.'}
    )
    assert isinstance(action, InformAction)
    assert action.text == 'Created 2 helper files.'


def test_escalate_threads_structured_attempts() -> None:
    action = _handle_communicate_tool(
        {
            'intent': 'escalate',
            'message': 'Stuck on import',
            'attempts': [
                {'action': 'rg --files', 'result': 'no match'},
                {'action': 'python -c "import x"', 'result': 'ModuleNotFoundError'},
            ],
            'specific_help_needed': 'Confirm the file path.',
        }
    )
    assert isinstance(action, EscalateToHumanAction)
    # Structured attempts are flattened to "action \u2192 result" lines.
    assert action.attempts_made == [
        'rg --files \u2192 no match',
        'python -c "import x" \u2192 ModuleNotFoundError',
    ]
    assert action.specific_help_needed == 'Confirm the file path.'


def test_escalate_falls_back_to_context_for_attempts() -> None:
    action = _handle_communicate_tool(
        {
            'intent': 'escalate',
            'message': 'stuck',
            'context': 'I tried rg, find, and grep; all empty.',
        }
    )
    assert isinstance(action, EscalateToHumanAction)
    assert action.attempts_made == ['I tried rg, find, and grep; all empty.']


def test_escalate_with_string_attempt() -> None:
    action = _handle_communicate_tool(
        {
            'intent': 'escalate',
            'message': 'stuck',
            'attempts': ['tried ripgrep, no matches'],
        }
    )
    assert isinstance(action, EscalateToHumanAction)
    assert action.attempts_made == ['tried ripgrep, no matches']


def test_unknown_intent_is_rejected() -> None:
    """Invalid intent values raise so the LLM learns instead of silent default."""
    with pytest.raises(FunctionCallValidationError) as excinfo:
        _handle_communicate_tool({'intent': 'bogus', 'message': 'x'})
    assert 'unknown intent' in str(excinfo.value).lower()


def test_empty_intent_defaults_to_clarification() -> None:
    """Missing intent is treated as clarification (lenient on omission)."""
    action = _handle_communicate_tool({'message': 'Hello?'})
    assert isinstance(action, ClarificationRequestAction)
    assert action.question == 'Hello?'
