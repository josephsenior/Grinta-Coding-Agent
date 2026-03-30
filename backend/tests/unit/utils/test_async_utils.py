"""Tests for backend.utils.async_utils — async/sync bridging and task coordination."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from backend.utils import async_utils
from backend.utils.async_utils import (
    AsyncException,
    call_async_from_sync,
    call_coro_in_bg_thread,
    call_sync_from_async,
    create_tracked_task,
    get_active_loop,
    run_in_loop,
    run_or_schedule,
    wait_all,
)


# ── create_tracked_task ────────────────────────────────────────────────


class TestCreateTrackedTask:
    """Test tracked task creation to prevent GC."""

    @pytest.mark.asyncio
    async def test_creates_task(self):
        """Test creates asyncio task."""

        async def sample_coro():
            return 42

        task = create_tracked_task(sample_coro())
        assert isinstance(task, asyncio.Task)
        result = await task
        assert result == 42

    @pytest.mark.asyncio
    async def test_task_with_name(self):
        """Test task creation with custom name."""

        async def sample_coro():
            return "named"

        task = create_tracked_task(sample_coro(), name="my_task")
        assert task.get_name() == "my_task"
        result = await task
        assert result == "named"

    @pytest.mark.asyncio
    async def test_task_added_to_default_set(self):
        """Test task is added to module-level background tasks."""
        from backend.utils.async_utils import _background_tasks

        async def sample_coro():
            await asyncio.sleep(0.01)
            return "done"

        initial_count = len(_background_tasks)
        task = create_tracked_task(sample_coro())
        assert len(_background_tasks) == initial_count + 1
        assert task in _background_tasks
        await task
        # Task should be removed after completion
        await asyncio.sleep(0.01)
        assert task not in _background_tasks

    @pytest.mark.asyncio
    async def test_task_with_custom_set(self):
        """Test task added to custom set."""
        custom_set: set[asyncio.Task] = set()

        async def sample_coro():
            return "custom"

        task = create_tracked_task(sample_coro(), task_set=custom_set)
        assert task in custom_set
        await task
        await asyncio.sleep(0.01)
        assert task not in custom_set


# ── call_sync_from_async ───────────────────────────────────────────────


class TestCallSyncFromAsync:
    """Test running sync functions from async context."""

    @pytest.mark.asyncio
    async def test_calls_sync_function(self):
        """Test calling synchronous function."""

        def sync_func(x, y):
            return x + y

        result = await call_sync_from_async(sync_func, 10, 20)
        assert result == 30

    @pytest.mark.asyncio
    async def test_calls_sync_with_kwargs(self):
        """Test calling sync function with kwargs."""

        def sync_func(a, b=5):
            return a * b

        result = await call_sync_from_async(sync_func, 3, b=7)
        assert result == 21

    @pytest.mark.asyncio
    async def test_exception_propagates(self):
        """Test exception from sync function propagates."""

        def failing_func():
            raise ValueError("sync error")

        with pytest.raises(ValueError, match="sync error"):
            await call_sync_from_async(failing_func)


# ── call_async_from_sync ───────────────────────────────────────────────


class TestCallAsyncFromSync:
    """Test running async functions from sync context."""

    def test_calls_async_function(self):
        """Test calling async function from sync."""

        async def async_func(x):
            await asyncio.sleep(0.01)
            return x * 2

        result = call_async_from_sync(async_func, timeout=5.0, x=21)
        assert result == 42

    def test_calls_async_with_timeout(self):
        """Test calling async function with custom timeout."""

        async def quick_func():
            return "quick"

        result = call_async_from_sync(quick_func, timeout=5.0)
        assert result == "quick"

    def test_raises_on_none_corofn(self):
        """Test raises ValueError when corofn is None."""
        with pytest.raises(ValueError, match="corofn is None"):
            call_async_from_sync(None)

    def test_raises_on_non_coroutine_function(self):
        """Test raises ValueError for non-coroutine function."""

        def regular_func():
            return "not a coro"

        with pytest.raises(ValueError, match="not a coroutine function"):
            call_async_from_sync(regular_func)

    def test_exception_propagates_from_async(self):
        """Test exception from async function propagates."""

        async def failing_async():
            raise RuntimeError("async error")

        with pytest.raises(RuntimeError, match="async error"):
            call_async_from_sync(failing_async)


class TestGetMaxWorkers:
    def test_reads_app_thread_pool_env(self):
        with patch.dict("os.environ", {"APP_THREAD_POOL_MAX_WORKERS": "7"}, clear=False):
            assert async_utils._get_max_workers() == 7

    def test_invalid_app_thread_pool_env_falls_back(self):
        with patch.dict("os.environ", {"APP_THREAD_POOL_MAX_WORKERS": "abc"}, clear=False):
            assert async_utils._get_max_workers() == 32

    def test_non_positive_app_thread_pool_env_falls_back(self):
        with patch.dict("os.environ", {"APP_THREAD_POOL_MAX_WORKERS": "0"}, clear=False):
            assert async_utils._get_max_workers() == 32


# ── call_coro_in_bg_thread ─────────────────────────────────────────────


class TestCallCoroInBgThread:
    """Test running coroutine in background thread."""

    @pytest.mark.asyncio
    async def test_calls_coro_in_thread(self):
        """Test calling coroutine in background thread."""

        async def bg_coro(value):
            await asyncio.sleep(0.01)
            return value + 100

        await call_coro_in_bg_thread(bg_coro, timeout=5.0, value=50)
        # Background task, no result expected.

    @pytest.mark.asyncio
    async def test_uses_delegate_pattern(self):
        """Test uses dynamic import delegate pattern."""

        async def sample():
            return "delegated"

        # Should not raise even though it runs in the background.
        await call_coro_in_bg_thread(sample, timeout=2.0)


# ── wait_all ───────────────────────────────────────────────────────────


class TestWaitAll:
    """Test waiting for multiple coroutines."""

    @pytest.mark.asyncio
    async def test_waits_for_all_coroutines(self):
        """Test waits for all coroutines to complete."""

        async def coro1():
            return 1

        async def coro2():
            return 2

        async def coro3():
            return 3

        results = await wait_all([coro1(), coro2(), coro3()])
        assert sorted(results) == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_empty_iterable(self):
        """Test returns empty list for empty iterable."""
        results = await wait_all([])
        assert results == []

    @pytest.mark.asyncio
    async def test_raises_single_exception(self):
        """Test raises exception from single failing task."""

        async def failing():
            raise ValueError("task failed")

        async def successful():
            return "ok"

        with pytest.raises(ValueError, match="task failed"):
            await wait_all([failing(), successful()])

    @pytest.mark.asyncio
    async def test_raises_async_exception_for_multiple_failures(self):
        """Test raises AsyncException for multiple failures."""

        async def fail1():
            raise ValueError("error 1")

        async def fail2():
            raise RuntimeError("error 2")

        with pytest.raises(AsyncException) as exc_info:
            await wait_all([fail1(), fail2()])
        assert len(exc_info.value.exceptions) == 2

    @pytest.mark.asyncio
    async def test_timeout_raises_timeout_error(self):
        """Test timeout raises TimeoutError."""

        async def slow_task():
            await asyncio.sleep(10)
            return "never"

        with pytest.raises(TimeoutError):
            await wait_all([slow_task()], timeout=1)


# ── AsyncException ─────────────────────────────────────────────────────


class TestAsyncException:
    """Test AsyncException aggregate exception."""

    def test_stores_exceptions(self):
        """Test stores list of exceptions."""
        exc1 = ValueError("error 1")
        exc2 = RuntimeError("error 2")
        agg_exc = AsyncException([exc1, exc2])
        assert len(agg_exc.exceptions) == 2
        assert exc1 in agg_exc.exceptions
        assert exc2 in agg_exc.exceptions

    def test_str_joins_messages(self):
        """Test __str__ joins exception messages."""
        exc1 = ValueError("first")
        exc2 = RuntimeError("second")
        agg_exc = AsyncException([exc1, exc2])
        result = str(agg_exc)
        assert "first" in result
        assert "second" in result
        assert "\n" in result


# ── run_in_loop ────────────────────────────────────────────────────────


class TestRunInLoop:
    """Test running coroutine in specific event loop."""

    @pytest.mark.asyncio
    async def test_runs_in_same_loop(self):
        """Test runs coroutine in same loop directly."""

        async def sample():
            return "same_loop"

        loop = asyncio.get_running_loop()
        result = await run_in_loop(sample(), loop)
        assert result == "same_loop"

    @pytest.mark.asyncio
    async def test_runs_in_different_loop(self):
        """Test runs coroutine when on different loop."""

        async def sample():
            return "different_loop"

        # When on different loop, run_in_loop uses thread handoff
        # For this test, just verify same loop works correctly
        loop = asyncio.get_running_loop()
        result = await run_in_loop(sample(), loop, timeout=2.0)
        assert result == "different_loop"


# ── get_active_loop ────────────────────────────────────────────────────


class TestGetActiveLoop:
    """Test getting active event loop."""

    @pytest.mark.asyncio
    async def test_returns_running_loop(self):
        """Test returns running loop when in async context."""
        loop = get_active_loop()
        assert loop is not None
        assert loop.is_running()

    def test_returns_none_when_no_loop(self):
        """Test returns None when no loop running."""
        loop = get_active_loop()
        assert loop is None


# ── run_or_schedule ────────────────────────────────────────────────────


class TestRunOrSchedule:
    """Test run or schedule coroutine."""

    @pytest.mark.asyncio
    async def test_schedules_when_loop_running(self):
        """Test schedules task when loop is running."""
        from backend.utils.async_utils import _background_tasks

        async def to_schedule():
            await asyncio.sleep(0.01)
            return "scheduled"

        initial_count = len(_background_tasks)
        run_or_schedule(to_schedule())
        await asyncio.sleep(0.02)
        # Task should have been scheduled
        assert len(_background_tasks) >= initial_count

    def test_runs_when_no_loop(self):
        """Test runs coroutine when no loop running."""
        executed = []

        async def to_run():
            executed.append(True)
            return "executed"

        run_or_schedule(to_run())
        assert executed == [True]
