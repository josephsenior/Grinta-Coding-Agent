"""Tests for backend.context.context_budget."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from backend.context.context_budget import ContextBudget, record_post_compact_baseline
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


def test_should_autocompact_when_estimate_exceeds_threshold():
    llm_config = SimpleNamespace(max_input_tokens=1_000, model='gpt-test')
    huge = _user_event('x' * 50_000, 1)
    budget = ContextBudget.from_events([huge], llm_config=llm_config)
    assert budget.should_autocompact is True


def test_post_compact_estimate_uses_post_boundary_events_not_api_tokens():
    llm_config = SimpleNamespace(max_input_tokens=200_000, model='claude-test')
    state = MagicMock()
    state.extra_data = {}
    events = [_user_event('hello', 1)]
    for i in range(2, 52):
        events.append(_user_event(f'chunk {i} ' * 50, i))

    def _set_extra(key, value, source='test'):
        state.extra_data[key] = value

    state.set_extra = _set_extra
    state.metrics = SimpleNamespace(
        token_usages=[SimpleNamespace(prompt_tokens=500_000, total_tokens=500_000)]
    )

    pre_compact = ContextBudget.from_events(events, llm_config=llm_config, state=state)
    assert pre_compact.estimated_tokens > 500_000

    post_boundary = events[-10:]
    record_post_compact_baseline(state, post_boundary)
    post_compact = ContextBudget.from_events(
        post_boundary, llm_config=llm_config, state=state
    )
    assert post_compact.estimated_tokens < pre_compact.estimated_tokens // 2
    assert post_compact.estimated_tokens < 500_000


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
    state.metrics = SimpleNamespace(
        token_usages=[SimpleNamespace(prompt_tokens=50_000, total_tokens=55_000)]
    )
    events = [_user_event('hello', 1)]

    budget = ContextBudget.from_events(events, llm_config=llm_config, state=state)

    assert budget.fixed_prompt_reserve_tokens == 6_000
    assert (
        budget.autocompact_threshold
        == 20_000 - DEFAULT_COMPACTION_RESERVED_SUMMARY_TOKENS - 6_000
    )
    assert budget.estimated_tokens < 8_000
