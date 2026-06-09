"""Tests for backend.context.context_budget."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from backend.context.context_budget import ContextBudget
from backend.core.constants import DEFAULT_COMPACTION_RESERVED_SUMMARY_TOKENS
from backend.ledger.action.message import MessageAction
from backend.ledger.event import EventSource


def _user_event(text: str, event_id: int) -> MessageAction:
    action = MessageAction(content=text)
    action.id = event_id
    action.source = EventSource.USER
    return action


def test_autocompact_threshold_reserves_summary_headroom():
    llm_config = SimpleNamespace(max_input_tokens=200_000, model='claude-test')
    budget = ContextBudget.from_events(
        [_user_event('hello', 1)],
        llm_config=llm_config,
    )
    assert budget.autocompact_threshold == 200_000 - DEFAULT_COMPACTION_RESERVED_SUMMARY_TOKENS
    assert budget.should_autocompact is False


def test_should_autocompact_when_estimate_exceeds_threshold():
    llm_config = SimpleNamespace(max_input_tokens=1_000, model='gpt-test')
    huge = _user_event('x' * 50_000, 1)
    budget = ContextBudget.from_events([huge], llm_config=llm_config)
    assert budget.should_autocompact is True
