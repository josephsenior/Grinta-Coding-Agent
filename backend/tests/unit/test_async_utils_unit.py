"""Tests for backend.utils.async_utils — Async bridging and task coordination."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from backend.utils.async_utils import (
    AsyncException,
    _collect_results,
    _handle_pending_tasks,
    call_async_from_sync,
    create_tracked_task,
    get_active_loop,
    wait_all,
)


# ── AsyncException ───────────────────────────────────────────────────


class TestAsyncException:
    def test_str_single(self):
        exc = AsyncException([ValueError("a")])
        assert str(exc) == "a"

    def test_str_multi(self):
        exc = AsyncException([ValueError("a"), TypeError("b")])
        assert "a" in str(exc)
        assert "b" in str(exc)

    def test_stores_exceptions(self):
        errs = [ValueError("x"), TypeError("y")]
        exc = AsyncException(errs)
        assert exc.exceptions is errs


# ── create_tracked_task ──────────────────────────────────────────────


class TestCreateTrackedTask:
    @pytest.mark.asyncio
    async def test_task_added_to_custom_set(self):
        bag: set[asyncio.Task] = set()

        async def noop():
            return 42

        task = create_tracked_task(noop(), task_set=bag)
        assert task in bag
        result = await task
        assert result == 42
        # After completion, done callback removes from set
        await asyncio.sleep(0)  # let callbacks run
        assert task not in bag

    @pytest.mark.asyncio
    async def test_task_with_name(self):
        bag: set[asyncio.Task] = set()

        async def noop():
            pass

        task = create_tracked_task(noop(), name="my_task", task_set=bag)
        assert task.get_name() == "my_task"
        await task

    @pytest.mark.asyncio
    async def test_default_set(self):
        """Task added to module-level _background_tasks by default."""
        from backend.utils import async_utils

        async def noop():
            return 1

        task = create_tracked_task(noop())
        assert task in async_utils._background_tasks
        await task
        await asyncio.sleep(0)
        assert task not in async_utils._background_tasks


# ── call_async_from_sync ─────────────────────────────────────────────


class TestCallAsyncFromSync:
    def test_none_raises(self):
        with pytest.raises(ValueError, match="corofn is None"):
            call_async_from_sync(None)

    def test_not_coroutine_raises(self):
        def sync_fn():
            pass

        with pytest.raises(ValueError, match="not a coroutine"):
            call_async_from_sync(sync_fn)

    def test_valid_coro(self):
        async def greet(name):
            return f"hi {name}"

        result = call_async_from_sync(greet, timeout=5.0, name="world")
        # On some platforms this may work; on others executor might be shut down.
        # We mainly test the validation paths above.
        assert result == "hi world"


# ── _collect_results ─────────────────────────────────────────────────


class TestCollectResults:
    @pytest.mark.asyncio
    async def test_all_success(self):
        async def val(x):
            return x

        tasks = [asyncio.create_task(val(i)) for i in range(3)]
        await asyncio.gather(*tasks)
        results = _collect_results(tasks)
        assert results == [0, 1, 2]

    @pytest.mark.asyncio
    async def test_single_error(self):
        async def fail():
            raise ValueError("boom")

        task = asyncio.create_task(fail())
        with pytest.raises(ValueError):
            await task
        with pytest.raises(ValueError, match="boom"):
            _collect_results([task])

    @pytest.mark.asyncio
    async def test_multi_error(self):
        async def fail_a():
            raise ValueError("a")

        async def fail_b():
            raise TypeError("b")

        t1 = asyncio.create_task(fail_a())
        t2 = asyncio.create_task(fail_b())
        await asyncio.sleep(0.05)  # let them finish
        with pytest.raises(AsyncException) as exc_info:
            _collect_results([t1, t2])
        assert len(exc_info.value.exceptions) == 2


# ── _handle_pending_tasks ────────────────────────────────────────────


class TestHandlePendingTasks:
    @pytest.mark.asyncio
    async def test_cancels_pending(self):
        async def slow():
            await asyncio.sleep(100)

        task = asyncio.create_task(slow())
        _handle_pending_tasks(done=set(), pending={task})
        # Task is cancelled but needs a loop tick to finalize
        assert task.cancelling() > 0 or task.cancelled()


# ── wait_all ─────────────────────────────────────────────────────────


class TestWaitAll:
    @pytest.mark.asyncio
    async def test_empty(self):
        result = await wait_all([])
        assert result == []

    @pytest.mark.asyncio
    async def test_success(self):
        async def val(x):
            return x

        result = await wait_all([val(1), val(2), val(3)])
        assert result == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_error(self):
        async def fail():
            raise ValueError("oops")

        with pytest.raises(ValueError, match="oops"):
            await wait_all([fail()])


# ── get_active_loop ──────────────────────────────────────────────────


class TestGetActiveLoop:
    @pytest.mark.asyncio
    async def test_returns_loop_when_running(self):
        loop = get_active_loop()
        assert loop is not None
        assert loop.is_running()

    def test_returns_none_when_not_running(self):
        # Outside an async context, there is no running loop
        loop = get_active_loop()
        assert loop is None
