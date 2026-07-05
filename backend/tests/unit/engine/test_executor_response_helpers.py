"""Executor response helper tests."""

from __future__ import annotations

from backend.engine.executor_response_helpers import (
    apply_malformed_tool_call_recovery,
    prepare_streamed_message_actions,
)
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


def test_apply_malformed_tool_call_recovery_clears_final_response() -> None:
    action = MessageAction(content='Continuing work.', final_response=True)

    apply_malformed_tool_call_recovery([action], malformed_tool_call_dropped=True)

    assert action.final_response is False


def test_apply_malformed_tool_call_recovery_noop_when_not_dropped() -> None:
    action = MessageAction(content='Done.', final_response=True)

    apply_malformed_tool_call_recovery([action], malformed_tool_call_dropped=False)

    assert action.final_response is True
