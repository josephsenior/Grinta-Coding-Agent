"""Stress tests for drain_step_barrier under concurrent background work."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest

from backend.orchestration.services.pending_action_service import PendingActionService
from backend.utils.async_helpers.async_utils import drain_step_barrier, run_or_schedule

pytestmark = pytest.mark.stress


def _make_pending_service() -> PendingActionService:
    from unittest.mock import MagicMock

    ctx = MagicMock()
    ctx.get_controller.return_value = MagicMock(event_stream=MagicMock())
    return PendingActionService(ctx, timeout=300.0)


@pytest.mark.asyncio
async def test_barrier_drains_many_background_tasks() -> None:
    """32 nested background tasks must drain within the deadline."""
    counter = {'done': 0}
    lock = asyncio.Lock()

    async def _leaf() -> None:
        await asyncio.sleep(0.01)
        async with lock:
            counter['done'] += 1

    async def _spawn(depth: int) -> None:
        if depth <= 0:
            await _leaf()
            return
        run_or_schedule(_spawn(depth - 1))
        await asyncio.sleep(0)

    for _ in range(8):
        run_or_schedule(_spawn(3))

    drained = await drain_step_barrier(timeout=5.0, poll_interval=0.02)
    assert drained is True
    assert counter['done'] == 8


@pytest.mark.asyncio
async def test_barrier_waits_for_pending_clear_under_load() -> None:
    """Pending rows cleared from background tasks must be visible to the barrier."""
    svc = _make_pending_service()
    actions = [SimpleNamespace(id=i) for i in range(24)]
    for action in actions:
        svc.set(cast(Any, action))

    async def _clear_batch(start: int, end: int) -> None:
        await asyncio.sleep(0.02)
        for idx in range(start, end):
            svc.clear_for_action(cast(Any, actions[idx]))

    for start in range(0, 24, 6):
        run_or_schedule(_clear_batch(start, min(start + 6, 24)))

    drained = await drain_step_barrier(
        has_outstanding=svc.has_outstanding,
        timeout=5.0,
        poll_interval=0.02,
    )
    assert drained is True
    assert svc.has_outstanding() is False


@pytest.mark.asyncio
async def test_barrier_times_out_when_pending_never_clears() -> None:
    """Outstanding pending past the deadline must return False, not hang."""
    svc = _make_pending_service()
    svc.set(cast(Any, SimpleNamespace(id=99)))

    drained = await drain_step_barrier(
        has_outstanding=svc.has_outstanding,
        timeout=0.15,
        poll_interval=0.03,
    )
    assert drained is False
    assert svc.has_outstanding() is True
