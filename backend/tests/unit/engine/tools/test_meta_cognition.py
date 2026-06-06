"""Unit tests for the simplified ask_user tool handler."""

from __future__ import annotations

import pytest

from backend.core.errors import FunctionCallValidationError
from backend.engine.tools._tool_handlers import _handle_ask_user_tool
from backend.engine.tools.meta_cognition import ASK_USER_TOOL_NAME, create_ask_user_tool
from backend.ledger.action import MessageAction


def test_create_ask_user_tool_schema() -> None:
    tool = create_ask_user_tool()
    fn = tool['function']

    assert fn['name'] == ASK_USER_TOOL_NAME
    assert fn['parameters']['required'] == ['questions']
    assert fn['parameters']['properties']['questions']['type'] == 'array'


def test_ask_user_builds_waiting_message_with_numbered_questions() -> None:
    action = _handle_ask_user_tool(
        {
            'questions': [
                'Which backend should I target?',
                'Should I keep the current schema?',
            ]
        }
    )

    assert isinstance(action, MessageAction)
    assert action.wait_for_response is True
    assert action.final_response is False
    assert action.content == (
        '1. Which backend should I target?\n'
        '2. Should I keep the current schema?'
    )


def test_ask_user_accepts_single_string_for_compatibility() -> None:
    action = _handle_ask_user_tool({'questions': 'Continue with this approach?'})

    assert isinstance(action, MessageAction)
    assert action.content == '1. Continue with this approach?'
    assert action.wait_for_response is True


@pytest.mark.parametrize('questions', [[], ['  ', ''], None])
def test_ask_user_rejects_empty_questions(questions: object) -> None:
    with pytest.raises(FunctionCallValidationError) as excinfo:
        _handle_ask_user_tool({'questions': questions})

    assert 'non-empty questions list' in str(excinfo.value)
