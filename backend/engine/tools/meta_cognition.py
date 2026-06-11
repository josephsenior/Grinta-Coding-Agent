"""User-input tool for the simplified agent protocol."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from backend.engine.contracts import ChatCompletionToolParam
from backend.engine.tools.common import create_tool_definition
from backend.inference.tool_names import ASK_USER_TOOL_NAME
from backend.ledger.action import MessageAction


def create_ask_user_tool() -> ChatCompletionToolParam:
    """Create the only model-facing communication tool."""
    return create_tool_definition(
        name=ASK_USER_TOOL_NAME,
        description=(
            'Ask the user one or more questions when input is required to continue. '
            'Calling this tool pauses the run until the user replies.'
        ),
        properties={
            'questions': {
                'type': 'array',
                'description': 'Questions to show the user.',
                'items': {'type': 'string'},
                'minItems': 1,
            },
        },
        required=['questions'],
    )


def _clean_questions(raw_questions: object) -> list[str]:
    if isinstance(raw_questions, str):
        questions = [raw_questions]
    elif isinstance(raw_questions, Sequence) and not isinstance(
        raw_questions, (bytes, bytearray)
    ):
        questions = [str(item) for item in raw_questions]
    else:
        questions = []
    return [question.strip() for question in questions if question.strip()]


def build_ask_user_action(arguments: Mapping[str, Any]) -> MessageAction:
    """Convert ask_user arguments into a pausing message action."""
    from backend.core.errors import FunctionCallValidationError

    questions = _clean_questions(arguments.get('questions'))
    if not questions:
        raise FunctionCallValidationError(
            'ask_user requires a non-empty questions list.'
        )

    content = '\n'.join(
        f'{idx}. {question}' for idx, question in enumerate(questions, start=1)
    )
    return MessageAction(content=content, wait_for_response=True)
