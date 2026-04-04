"""Tests for backend.utils.search_utils and backend.utils.async_utils."""

from __future__ import annotations

import asyncio
import base64
import unittest
from dataclasses import dataclass
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

from backend.utils.search_utils import iterate, offset_to_page_id, page_id_to_offset

# ---------------------------------------------------------------------------
# search_utils
# ---------------------------------------------------------------------------


class TestOffsetToPageId(unittest.TestCase):
    def test_has_next_returns_encoded(self):
        pid = offset_to_page_id(42, has_next=True)
        self.assertIsNotNone(pid)
        assert pid is not None
        decoded = int(base64.b64decode(pid).decode())
        self.assertEqual(decoded, 42)

    def test_no_next_returns_none(self):
        self.assertIsNone(offset_to_page_id(42, has_next=False))

    def test_zero_offset(self):
        pid = offset_to_page_id(0, has_next=True)
        assert pid is not None
        decoded = int(base64.b64decode(pid).decode())
        self.assertEqual(decoded, 0)


class TestPageIdToOffset(unittest.TestCase):
    def test_valid_page_id(self):
        pid = base64.b64encode(b'100').decode()
        self.assertEqual(page_id_to_offset(pid), 100)

    def test_none_returns_zero(self):
        self.assertEqual(page_id_to_offset(None), 0)

    def test_roundtrip(self):
        for offset in (0, 1, 50, 9999):
            pid = offset_to_page_id(offset, has_next=True)
            self.assertEqual(page_id_to_offset(pid), offset)


class TestIterate(unittest.IsolatedAsyncioTestCase):
    async def test_single_page(self):
        @dataclass
        class ResultSet:
            results: list
            next_page_id: str | None = None

        mock_fn = AsyncMock(
            return_value=ResultSet(results=[1, 2, 3], next_page_id=None)
        )
        items = [item async for item in iterate(mock_fn)]
        self.assertEqual(items, [1, 2, 3])
        mock_fn.assert_awaited_once()

    async def test_multi_page(self):
        @dataclass
        class ResultSet:
            results: list
            next_page_id: str | None = None

        page_id = base64.b64encode(b'10').decode()
        mock_fn = AsyncMock(
            side_effect=[
                ResultSet(results=['a', 'b'], next_page_id=page_id),
                ResultSet(results=['c'], next_page_id=None),
            ]
        )
        items = [item async for item in iterate(mock_fn)]
        self.assertEqual(items, ['a', 'b', 'c'])
        self.assertEqual(mock_fn.await_count, 2)

    async def test_empty_first_page(self):
        @dataclass
        class ResultSet:
            results: list
            next_page_id: str | None = None

        mock_fn = AsyncMock(return_value=ResultSet(results=[], next_page_id=None))
        items = [item async for item in iterate(mock_fn)]
        self.assertEqual(items, [])


# ---------------------------------------------------------------------------
# async_utils
# ---------------------------------------------------------------------------

from backend.utils.async_utils import (  # noqa: E402
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


class TestCreateTrackedTask(unittest.IsolatedAsyncioTestCase):
    async def test_tracked_task_completes(self):
        results = []

        async def coro():
            results.append(1)
            return 42

        task_set: set[asyncio.Task] = set()
        task = create_tracked_task(coro(), task_set=task_set)
        self.assertIn(task, task_set)
        result = await task
        self.assertEqual(result, 42)
        # After completion, task is removed from set
        await asyncio.sleep(0)  # Let done callback fire
        self.assertNotIn(task, task_set)

    async def test_tracked_task_default_set(self):
        async def noop():
            pass

        task = create_tracked_task(noop(), name='test-task')
        await task


class TestCallSyncFromAsync(unittest.IsolatedAsyncioTestCase):
    async def test_sync_function(self):
        def add(a, b):
            return a + b

        result = await call_sync_from_async(add, 3, 4)
        self.assertEqual(result, 7)


class TestCallAsyncFromSync(unittest.TestCase):
    def test_valid_coroutine(self):
        async def greet(name):
            return f'hello {name}'

        result = call_async_from_sync(greet, timeout=5, name='world')
        self.assertEqual(result, 'hello world')

    def test_none_raises(self):
        with self.assertRaises(ValueError):
            call_async_from_sync(None)

    def test_non_coroutine_raises(self):
        with self.assertRaises(ValueError):
            call_async_from_sync(cast(Any, lambda: 1))


class TestWaitAll(unittest.IsolatedAsyncioTestCase):
    async def test_all_succeed(self):
        async def double(x):
            return x * 2

        results = await wait_all([double(1), double(2), double(3)])
        self.assertEqual(results, [2, 4, 6])

    async def test_empty_iterable(self):
        results = await wait_all([])
        self.assertEqual(results, [])

    async def test_single_error_raises(self):
        async def fail():
            raise RuntimeError('boom')

        with self.assertRaises(RuntimeError):
            await wait_all([fail()])

    async def test_multiple_errors(self):
        async def fail(msg):
            raise RuntimeError(msg)

        with self.assertRaises(AsyncException):
            await wait_all([fail('a'), fail('b')])


class TestAsyncException(unittest.TestCase):
    def test_str(self):
        exc = AsyncException([ValueError('x'), TypeError('y')])
        self.assertEqual(str(exc), 'x\ny')

    def test_exceptions_attr(self):
        errs = [ValueError('a')]
        exc = AsyncException(errs)
        self.assertIs(exc.exceptions, errs)


class TestCollectResults(unittest.IsolatedAsyncioTestCase):
    async def test_collect_success(self):
        async def val(x):
            return x

        tasks = [asyncio.create_task(val(i)) for i in range(3)]
        await asyncio.gather(*tasks)
        results = _collect_results(tasks)
        self.assertEqual(results, [0, 1, 2])


class TestGetActiveLoop(unittest.IsolatedAsyncioTestCase):
    async def test_returns_running_loop(self):
        loop = get_active_loop()
        self.assertIsNotNone(loop)
        assert loop is not None
        self.assertTrue(loop.is_running())


class TestGetActiveLoopSync(unittest.TestCase):
    def test_returns_none_outside_loop(self):
        self.assertIsNone(get_active_loop())


class TestRunOrSchedule(unittest.IsolatedAsyncioTestCase):
    async def test_with_active_loop(self):
        results = []

        async def add():
            results.append(1)

        run_or_schedule(add())
        await asyncio.sleep(0.05)
        self.assertEqual(results, [1])


class TestHandlePendingTasks(unittest.TestCase):
    def test_cancels_pending(self):
        task = MagicMock()
        task.get_coro.return_value = MagicMock(__name__='slow_task')
        _handle_pending_tasks(done=set(), pending={task})
        task.cancel.assert_called_once()


if __name__ == '__main__':
    unittest.main()
