import asyncio

import pytest

from backend.inference.comparison_budget import AttemptBudget, BudgetExceeded
from backend.inference.comparison_scope import active_budget, run_budgeted


def test_overshoot_stops_next_operation():
    budget = AttemptBudget(tokens=20)
    budget.charge(10, 5)
    with pytest.raises(BudgetExceeded, match='token_limit'):
        budget.charge(4, 3)
    assert budget.snapshot()['token_overshoot'] == 2


def test_deadline_cancels_running_operation_and_restores_default_scope():
    stopped = []

    async def work():
        assert active_budget.get() is not None
        try:
            await asyncio.sleep(10)
        finally:
            stopped.append(True)

    async def check():
        with pytest.raises(BudgetExceeded, match='time_limit'):
            await run_budgeted(work, AttemptBudget(seconds=0.03))
        assert active_budget.get() is None

    asyncio.run(check())
    assert stopped == [True]


def test_token_limit_cancels_before_another_turn():
    async def work():
        active_budget.get().charge(15, 5)
        pytest.fail('continued after limit')

    with pytest.raises(BudgetExceeded, match='token_limit'):
        asyncio.run(run_budgeted(work, AttemptBudget(tokens=20)))


def test_subscription_hook_counts_reported_usage_once():
    from backend.inference.clients.chatgpt_plan import ChatGPTPlanClient

    budget = AttemptBudget(tokens=50)
    token = active_budget.set(budget)
    try:
        ChatGPTPlanClient('gpt-6.1-sol')._response_from_events(
            [
                {
                    'type': 'response.completed',
                    'response': {
                        'output': [],
                        'usage': {
                            'input_tokens': 10,
                            'output_tokens': 5,
                            'output_tokens_details': {'reasoning_tokens': 3},
                        },
                    },
                }
            ]
        )
        assert budget.used == 15
    finally:
        active_budget.reset(token)
