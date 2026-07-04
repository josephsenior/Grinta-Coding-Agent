"""Executor response helper tests."""

from backend.engine.executor_response_helpers import prepare_streamed_message_actions
from backend.ledger.action import MessageAction


def test_prepare_streamed_message_actions_strips_duplicate_thought() -> None:
    thought = 'Planning the next implementation phase.'
    actions = [
        MessageAction(
            content='Starting now.',
            thought=thought,
            final_response=True,
        )
    ]
    prepare_streamed_message_actions(
        actions,
        streamed_thinking_text=thought,
    )
    assert actions[0].thought == ''
    assert actions[0].content == 'Starting now.'


def test_prepare_streamed_message_actions_keeps_distinct_thought() -> None:
    actions = [
        MessageAction(
            content='Done.',
            thought='Different follow-up thought.',
            final_response=True,
        )
    ]
    prepare_streamed_message_actions(
        actions,
        streamed_thinking_text='Streamed reasoning only.',
    )
    assert actions[0].thought == 'Different follow-up thought.'


def test_prepare_streamed_message_actions_does_not_suppress_content() -> None:
    actions = [
        MessageAction(
            content='Final answer.',
            final_response=True,
        )
    ]
    prepare_streamed_message_actions(
        actions,
        streamed_visible_text='Final answer.',
    )
    assert actions[0].suppress_cli is False
    assert actions[0].content == 'Final answer.'
