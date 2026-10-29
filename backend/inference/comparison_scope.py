"""Opt-in aggregate comparison budget; normal Grinta has no active scope."""

import asyncio
from contextvars import ContextVar

active_budget = ContextVar('comparison_attempt_budget', default=None)


async def run_budgeted(operation, budget):
    budget.start()
    token = active_budget.set(budget)
    task = asyncio.create_task(operation())
    try:
        while not task.done():
            budget.check()
            await asyncio.wait({task}, timeout=min(0.05, budget.remaining))
        result = await task
        budget.check()
        return result
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        active_budget.reset(token)
