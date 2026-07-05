"""Tests for backend.context.context_budget."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from backend.context.context_budget import (
    ContextBudget,
    estimate_boundary_event_tokens,
)
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
    assert (
        budget.autocompact_threshold
        == 200_000 - DEFAULT_COMPACTION_RESERVED_SUMMARY_TOKENS
    )
    assert budget.should_autocompact is False


def test_should_autocompact_when_boundary_tokens_exceed_threshold():
    llm_config = SimpleNamespace(max_input_tokens=1_000, model='gpt-test')
    huge = _user_event('x' * 50_000, 1)
    budget = ContextBudget.from_events([huge], llm_config=llm_config)
    assert budget.should_autocompact is True


def test_budget_uses_boundary_tokens_not_api_cache():
    llm_config = SimpleNamespace(max_input_tokens=200_000, model='claude-test')
    state = MagicMock()
    state.extra_data = {
        'prompt_token_accounting': {
            'static_prompt_tokens': 2_000,
            'tool_schema_tokens': 3_000,
            'context_packet_tokens': 1_000,
            'dynamic_history_tokens': 80_000,
        }
    }
    state.metrics = SimpleNamespace(
        token_usages=[SimpleNamespace(prompt_tokens=500_000, total_tokens=500_000)]
    )
    events = [_user_event('hello', 1)]

    budget = ContextBudget.from_events(events, llm_config=llm_config, state=state)
    full = estimate_boundary_event_tokens(events, llm_config=llm_config)

    assert budget.estimated_tokens == full
    assert budget.estimated_tokens < 5_000


def test_budget_uses_dynamic_history_and_fixed_prompt_reserve() -> None:
    llm_config = SimpleNamespace(max_input_tokens=20_000, model='test-model')
    state = MagicMock()
    state.extra_data = {
        'prompt_token_accounting': {
            'static_prompt_tokens': 2_000,
            'tool_schema_tokens': 3_000,
            'context_packet_tokens': 1_000,
            'dynamic_history_tokens': 7_000,
        }
    }
    events = [_user_event('hello', 1)]

    budget = ContextBudget.from_events(events, llm_config=llm_config, state=state)

    assert budget.fixed_prompt_reserve_tokens == 6_000
    assert (
        budget.autocompact_threshold
        == 20_000 - DEFAULT_COMPACTION_RESERVED_SUMMARY_TOKENS - 6_000
    )
    assert budget.estimated_tokens < 8_000
