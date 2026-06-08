"""Stress tests for parallel pending-action lifecycle."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from backend.orchestration.services.pending_action_service import PendingActionService

pytestmark = pytest.mark.stress


def _make_service() -> PendingActionService:
    ctx = MagicMock()
    ctx.get_controller.return_value = MagicMock(event_stream=MagicMock())
    return PendingActionService(ctx, timeout=300.0)


@pytest.mark.asyncio
async def test_parallel_clear_for_action_monotonic_decrease() -> None:
    """Sixteen concurrent clears must not leave ghost outstanding rows."""
    svc = _make_service()
    actions = [SimpleNamespace(id=i) for i in range(16)]
    for action in actions:
        svc.set(cast(Any, action))

    assert svc.has_outstanding() is True

    async def _clear_one(action: SimpleNamespace) -> None:
        await asyncio.sleep(0.001 * action.id)
        svc.clear_for_action(cast(Any, action))

    await asyncio.gather(*[_clear_one(action) for action in actions])

    assert svc.has_outstanding() is False
    for action in actions:
        assert svc.peek_for_cause(action.id) is None


@pytest.mark.asyncio
async def test_clear_primary_does_not_wipe_siblings_under_load() -> None:
    """clear_primary must only remove the latest id while siblings remain."""
    svc = _make_service()
    actions = [SimpleNamespace(id=i) for i in range(8)]
    for action in actions:
        svc.set(cast(Any, action))

    outstanding_counts: list[int] = []

    async def _clear_primary_repeatedly() -> None:
        for _ in range(4):
            svc.clear_primary()
            outstanding_counts.append(
                sum(1 for action in actions if svc.peek_for_cause(action.id) is not None)
            )
            await asyncio.sleep(0.001)

    await _clear_primary_repeatedly()

    assert outstanding_counts[0] == 7
    assert outstanding_counts[-1] == 4
    assert svc.has_outstanding() is True


@pytest.mark.asyncio
async def test_interleaved_pop_for_cause_under_concurrency() -> None:
    """pop_for_cause from concurrent workers must resolve the correct rows."""
    svc = _make_service()
    actions = [SimpleNamespace(id=i) for i in range(32)]
    for action in actions:
        svc.set(cast(Any, action))

    async def _pop_one(action: SimpleNamespace) -> None:
        await asyncio.sleep(0.001 * (action.id % 5))
        popped = svc.pop_for_cause(action.id)
        assert popped is action

    await asyncio.gather(*[_pop_one(action) for action in actions])
    assert svc.has_outstanding() is False


@pytest.mark.asyncio
async def test_set_and_clear_all_race_leaves_no_ghost_rows() -> None:
    """Concurrent set + clear_all must end with a consistent empty map."""
    svc = _make_service()

    async def _register_batch(start: int) -> None:
        for idx in range(start, start + 8):
            svc.set(cast(Any, SimpleNamespace(id=idx)))

    async def _clear_loop() -> None:
        for _ in range(5):
            await asyncio.sleep(0.002)
            svc.clear_all()

    await asyncio.gather(_register_batch(0), _register_batch(100), _clear_loop())
    assert svc.has_outstanding() is False
