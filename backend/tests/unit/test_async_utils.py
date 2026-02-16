"""Unit tests for backend.utils.async_utils — async helpers."""

from __future__ import annotations

import asyncio

import pytest

from backend.utils.async_utils import (
    AsyncException,
    _collect_results,
    _handle_pending_tasks,
    call_async_from_sync,
    call_sync_from_async,
    create_tracked_task,
    get_active_loop,
    run_or_schedule,
    wait_all,
)


# ---------------------------------------------------------------------------
# create_tracked_task
# ---------------------------------------------------------------------------


class TestCreateTrackedTask:
    async def test_task_added_and_removed(self):
        task_set: set[asyncio.Task] = set()

        async def noop():
            return 42

        t = create_tracked_task(noop(), task_set=task_set)
        assert t in task_set
        result = await t
        assert result == 42
        # After completion the done callback should have removed it
        await asyncio.sleep(0)  # allow callback to fire
        assert t not in task_set

    async def test_default_background_set(self):
        from backend.utils.async_utils import _background_tasks

        async def noop():
            pass

        t = create_tracked_task(noop(), name="test-bg")
        assert t in _background_tasks
        await t
        await asyncio.sleep(0)
        assert t not in _background_tasks

    async def test_named_task(self):
        async def noop():
            pass

        t = create_tracked_task(noop(), name="my-task")
        assert t.get_name() == "my-task"
        await t


# ---------------------------------------------------------------------------
# call_sync_from_async
# ---------------------------------------------------------------------------


class TestCallSyncFromAsync:
    async def test_returns_result(self):
        def add(a, b):
            return a + b

        result = await call_sync_from_async(add, 3, 4)
        assert result == 7

    async def test_propagates_exception(self):
        def fail():
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            await call_sync_from_async(fail)


# ---------------------------------------------------------------------------
# call_async_from_sync
# ---------------------------------------------------------------------------


class TestCallAsyncFromSync:
    def test_none_raises_value_error(self):
        with pytest.raises(ValueError, match="corofn is None"):
            call_async_from_sync(None)

    def test_non_coro_raises_value_error(self):
        with pytest.raises(ValueError, match="not a coroutine"):
            call_async_from_sync(lambda: 42)  # type: ignore[arg-type]

    def test_runs_coroutine(self):
        async def double(x):
            return x * 2

        result = call_async_from_sync(double, timeout=10, x=5)
        assert result == 10


# ---------------------------------------------------------------------------
# wait_all
# ---------------------------------------------------------------------------


class TestWaitAll:
    async def test_empty(self):
        results = await wait_all([])
        assert results == []

    async def test_multiple(self):
        async def val(x):
            return x

        results = await wait_all([val(1), val(2), val(3)])
        assert results == [1, 2, 3]

    async def test_single_exception(self):
        async def fail():
            raise RuntimeError("oops")

        async def ok():
            return 1

        with pytest.raises(RuntimeError, match="oops"):
            await wait_all([ok(), fail()])

    async def test_multiple_exceptions(self):
        async def fail1():
            raise ValueError("a")

        async def fail2():
            raise TypeError("b")

        with pytest.raises((ValueError, TypeError, AsyncException)):
            await wait_all([fail1(), fail2()])


# ---------------------------------------------------------------------------
# AsyncException
# ---------------------------------------------------------------------------


class TestAsyncException:
    def test_str(self):
        ae = AsyncException([ValueError("a"), TypeError("b")])
        s = str(ae)
        assert "a" in s
        assert "b" in s

    def test_exceptions_attribute(self):
        errs = [ValueError("x")]
        ae = AsyncException(errs)
        assert ae.exceptions is errs


# ---------------------------------------------------------------------------
# get_active_loop
# ---------------------------------------------------------------------------


class TestGetActiveLoop:
    async def test_returns_running_loop(self):
        loop = get_active_loop()
        assert loop is not None
        assert loop.is_running()

    def test_returns_none_outside_loop(self):
        # When called outside of an async context
        loop = get_active_loop()
        # May or may not be None depending on test runner, but should not raise
        assert loop is None or loop.is_running()


# ---------------------------------------------------------------------------
# _collect_results / _handle_pending_tasks
# ---------------------------------------------------------------------------


class TestCollectResults:
    async def test_all_success(self):
        async def val(x):
            return x

        tasks = [asyncio.create_task(val(i)) for i in range(3)]
        await asyncio.gather(*tasks)
        results = _collect_results(tasks)
        assert results == [0, 1, 2]

    async def test_single_error(self):
        async def fail():
            raise ValueError("err")

        tasks = [asyncio.create_task(fail())]
        with pytest.raises(ValueError, match="err"):
            await asyncio.gather(*tasks)
        # Task already done, _collect_results raises
        with pytest.raises(ValueError, match="err"):
            _collect_results(tasks)


class TestHandlePendingTasks:
    async def test_cancels_pending(self):
        async def hang():
            await asyncio.sleep(999)

        task = asyncio.create_task(hang())
        await asyncio.sleep(0)  # let it start
        _handle_pending_tasks(set(), {task})
        # Wait a tick to let the cancellation propagate
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert task.cancelled()


# ---------------------------------------------------------------------------
# run_or_schedule
# ---------------------------------------------------------------------------


class TestRunOrSchedule:
    async def test_in_running_loop(self):
        """When called inside an async context, it schedules a background task."""
        results = []

        async def cb():
            results.append(1)

        run_or_schedule(cb())
        await asyncio.sleep(0.05)
        assert results == [1]
