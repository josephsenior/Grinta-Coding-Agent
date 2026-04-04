"""Comprehensive tests for backend.core.retry_queue module.

Tests RetryTask data model, InMemoryRetryBackend, RetryQueue wrapper,
and get_retry_queue singleton factory.
"""

from __future__ import annotations

import time
import unittest
from unittest.mock import patch

from backend.core.retry_queue import (
    BaseRetryBackend,
    InMemoryRetryBackend,
    RetryQueue,
    RetryTask,
    get_retry_queue,
)


class TestRetryTask(unittest.TestCase):
    """Tests for RetryTask dataclass."""

    def test_creation_minimal(self):
        task = RetryTask(
            id='task-1',
            controller_id='ctrl-1',
            payload={'action': 'restart'},
            reason='timeout',
        )
        self.assertEqual(task.id, 'task-1')
        self.assertEqual(task.controller_id, 'ctrl-1')
        self.assertEqual(task.payload, {'action': 'restart'})
        self.assertEqual(task.reason, 'timeout')
        self.assertEqual(task.attempts, 0)
        self.assertEqual(task.max_attempts, 3)
        self.assertIsNone(task.last_error)
        self.assertEqual(task.metadata, {})

    def test_creation_full(self):
        task = RetryTask(
            id='task-2',
            controller_id='ctrl-2',
            payload={'key': 'val'},
            reason='network error',
            attempts=2,
            max_attempts=5,
            next_attempt_at=1000.0,
            created_at=900.0,
            last_error='Connection refused',
            metadata={'priority': 'high'},
        )
        self.assertEqual(task.attempts, 2)
        self.assertEqual(task.max_attempts, 5)
        self.assertEqual(task.next_attempt_at, 1000.0)
        self.assertEqual(task.created_at, 900.0)
        self.assertEqual(task.last_error, 'Connection refused')
        self.assertEqual(task.metadata, {'priority': 'high'})

    def test_to_dict(self):
        task = RetryTask(
            id='task-3',
            controller_id='ctrl-3',
            payload={'x': 1},
            reason='test',
            attempts=1,
            max_attempts=4,
            next_attempt_at=500.0,
            created_at=400.0,
            last_error='err',
            metadata={'tag': 'a'},
        )
        d = task.to_dict()
        self.assertEqual(d['id'], 'task-3')
        self.assertEqual(d['controller_id'], 'ctrl-3')
        self.assertEqual(d['payload'], {'x': 1})
        self.assertEqual(d['reason'], 'test')
        self.assertEqual(d['attempts'], 1)
        self.assertEqual(d['max_attempts'], 4)
        self.assertEqual(d['next_attempt_at'], 500.0)
        self.assertEqual(d['created_at'], 400.0)
        self.assertEqual(d['last_error'], 'err')
        self.assertEqual(d['metadata'], {'tag': 'a'})

    def test_from_dict_full(self):
        data = {
            'id': 'task-4',
            'controller_id': 'ctrl-4',
            'payload': {'y': 2},
            'reason': 'retry',
            'attempts': 3,
            'max_attempts': 10,
            'next_attempt_at': 600.0,
            'created_at': 550.0,
            'last_error': 'timeout',
            'metadata': {'env': 'prod'},
        }
        task = RetryTask.from_dict(data)
        self.assertEqual(task.id, 'task-4')
        self.assertEqual(task.controller_id, 'ctrl-4')
        self.assertEqual(task.payload, {'y': 2})
        self.assertEqual(task.reason, 'retry')
        self.assertEqual(task.attempts, 3)
        self.assertEqual(task.max_attempts, 10)
        self.assertEqual(task.next_attempt_at, 600.0)
        self.assertEqual(task.created_at, 550.0)
        self.assertEqual(task.last_error, 'timeout')
        self.assertEqual(task.metadata, {'env': 'prod'})

    def test_from_dict_minimal(self):
        data = {'id': 'task-5', 'controller_id': 'ctrl-5'}
        task = RetryTask.from_dict(data)
        self.assertEqual(task.id, 'task-5')
        self.assertEqual(task.controller_id, 'ctrl-5')
        self.assertEqual(task.payload, {})
        self.assertEqual(task.reason, '')
        self.assertEqual(task.attempts, 0)
        self.assertEqual(task.max_attempts, 3)
        self.assertIsNone(task.last_error)
        self.assertEqual(task.metadata, {})

    def test_round_trip(self):
        original = RetryTask(
            id='rt-1',
            controller_id='ctrl-rt',
            payload={'cmd': 'deploy'},
            reason='transient',
            attempts=2,
            max_attempts=5,
            next_attempt_at=1234.0,
            created_at=1200.0,
            last_error='500',
            metadata={'region': 'us-east'},
        )
        restored = RetryTask.from_dict(original.to_dict())
        self.assertEqual(original.id, restored.id)
        self.assertEqual(original.controller_id, restored.controller_id)
        self.assertEqual(original.payload, restored.payload)
        self.assertEqual(original.reason, restored.reason)
        self.assertEqual(original.attempts, restored.attempts)
        self.assertEqual(original.max_attempts, restored.max_attempts)
        self.assertEqual(original.next_attempt_at, restored.next_attempt_at)
        self.assertEqual(original.created_at, restored.created_at)
        self.assertEqual(original.last_error, restored.last_error)
        self.assertEqual(original.metadata, restored.metadata)


class TestBaseRetryBackend(unittest.IsolatedAsyncioTestCase):
    """Tests for BaseRetryBackend abstract interface."""

    async def test_schedule_not_implemented(self):
        backend = BaseRetryBackend()
        task = RetryTask(id='t', controller_id='c', payload={}, reason='r')
        with self.assertRaises(NotImplementedError):
            await backend.schedule(task)

    async def test_fetch_ready_not_implemented(self):
        backend = BaseRetryBackend()
        with self.assertRaises(NotImplementedError):
            await backend.fetch_ready('ctrl', 5)

    async def test_mark_success_not_implemented(self):
        backend = BaseRetryBackend()
        task = RetryTask(id='t', controller_id='c', payload={}, reason='r')
        with self.assertRaises(NotImplementedError):
            await backend.mark_success(task)

    async def test_mark_failure_not_implemented(self):
        backend = BaseRetryBackend()
        task = RetryTask(id='t', controller_id='c', payload={}, reason='r')
        with self.assertRaises(NotImplementedError):
            await backend.mark_failure(task, 5.0)

    async def test_dead_letter_not_implemented(self):
        backend = BaseRetryBackend()
        task = RetryTask(id='t', controller_id='c', payload={}, reason='r')
        with self.assertRaises(NotImplementedError):
            await backend.dead_letter(task)


class TestInMemoryRetryBackend(unittest.IsolatedAsyncioTestCase):
    """Tests for InMemoryRetryBackend."""

    def setUp(self):
        self.backend = InMemoryRetryBackend()

    async def test_schedule_stores_task(self):
        task = RetryTask(id='t1', controller_id='ctrl', payload={'a': 1}, reason='test')
        result = await self.backend.schedule(task)
        self.assertEqual(result.id, 't1')
        self.assertIn('t1', self.backend._tasks)

    async def test_schedule_returns_same_task(self):
        task = RetryTask(id='t2', controller_id='ctrl', payload={}, reason='test')
        result = await self.backend.schedule(task)
        self.assertIs(result, task)

    async def test_fetch_ready_returns_due_tasks(self):
        task = RetryTask(
            id='t3',
            controller_id='ctrl',
            payload={},
            reason='test',
            next_attempt_at=time.time() - 10,  # Past due
        )
        await self.backend.schedule(task)

        ready = await self.backend.fetch_ready('ctrl', 5)
        self.assertEqual(len(ready), 1)
        self.assertEqual(ready[0].id, 't3')
        self.assertEqual(ready[0].attempts, 1)  # Incremented

    async def test_fetch_ready_skips_future_tasks(self):
        task = RetryTask(
            id='t4',
            controller_id='ctrl',
            payload={},
            reason='test',
            next_attempt_at=time.time() + 3600,  # Far in the future
        )
        await self.backend.schedule(task)

        ready = await self.backend.fetch_ready('ctrl', 5)
        self.assertEqual(len(ready), 0)

    async def test_fetch_ready_respects_limit(self):
        for i in range(5):
            task = RetryTask(
                id=f't{i}',
                controller_id='ctrl',
                payload={},
                reason='test',
                next_attempt_at=time.time() - 10,
            )
            await self.backend.schedule(task)

        ready = await self.backend.fetch_ready('ctrl', 2)
        self.assertEqual(len(ready), 2)

    async def test_fetch_ready_filters_by_controller(self):
        task_a = RetryTask(
            id='ta',
            controller_id='ctrl-a',
            payload={},
            reason='test',
            next_attempt_at=time.time() - 10,
        )
        task_b = RetryTask(
            id='tb',
            controller_id='ctrl-b',
            payload={},
            reason='test',
            next_attempt_at=time.time() - 10,
        )
        await self.backend.schedule(task_a)
        await self.backend.schedule(task_b)

        ready_a = await self.backend.fetch_ready('ctrl-a', 5)
        self.assertEqual(len(ready_a), 1)
        self.assertEqual(ready_a[0].id, 'ta')

    async def test_mark_success_removes_task(self):
        task = RetryTask(id='ts', controller_id='ctrl', payload={}, reason='test')
        await self.backend.schedule(task)
        self.assertIn('ts', self.backend._tasks)

        await self.backend.mark_success(task)
        self.assertNotIn('ts', self.backend._tasks)

    async def test_mark_failure_reschedules(self):
        task = RetryTask(
            id='tf',
            controller_id='ctrl',
            payload={},
            reason='test',
            attempts=1,
            max_attempts=3,
        )
        await self.backend.schedule(task)

        result = await self.backend.mark_failure(task, 30.0)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertGreater(result.next_attempt_at, time.time())
        self.assertIn('tf', self.backend._tasks)

    async def test_mark_failure_dead_letters_exhausted_task(self):
        task = RetryTask(
            id='td',
            controller_id='ctrl',
            payload={},
            reason='test',
            attempts=3,
            max_attempts=3,
        )
        await self.backend.schedule(task)

        result = await self.backend.mark_failure(task, 10.0)
        self.assertIsNone(result)
        self.assertNotIn('td', self.backend._tasks)
        self.assertEqual(len(self.backend._dead_letter), 1)
        self.assertEqual(self.backend._dead_letter[0].id, 'td')

    async def test_dead_letter_moves_task(self):
        task = RetryTask(id='dl', controller_id='ctrl', payload={}, reason='fatal')
        await self.backend.schedule(task)
        self.assertIn('dl', self.backend._tasks)

        await self.backend.dead_letter(task)
        self.assertNotIn('dl', self.backend._tasks)
        self.assertEqual(len(self.backend._dead_letter), 1)

    async def test_fetch_ready_empty_queue(self):
        ready = await self.backend.fetch_ready('ctrl', 5)
        self.assertEqual(ready, [])

    async def test_mark_success_nonexistent_task(self):
        task = RetryTask(
            id='nonexistent', controller_id='ctrl', payload={}, reason='test'
        )
        # Should not raise
        await self.backend.mark_success(task)

    async def test_multiple_schedule_same_id(self):
        task = RetryTask(
            id='dup',
            controller_id='ctrl',
            payload={'v': 1},
            reason='test',
            next_attempt_at=time.time() - 10,
        )
        await self.backend.schedule(task)
        task2 = RetryTask(
            id='dup',
            controller_id='ctrl',
            payload={'v': 2},
            reason='test2',
            next_attempt_at=time.time() - 10,
        )
        await self.backend.schedule(task2)
        # Latest task should be stored
        self.assertEqual(self.backend._tasks['dup'].payload, {'v': 2})


class TestRetryQueue(unittest.IsolatedAsyncioTestCase):
    """Tests for RetryQueue high-level wrapper."""

    def setUp(self):
        self.backend = InMemoryRetryBackend()
        self.queue = RetryQueue(
            self.backend,
            base_delay=1.0,
            max_delay=60.0,
            max_retries=3,
            poll_interval=0.5,
        )

    async def test_schedule_creates_task(self):
        task = await self.queue.schedule(
            controller_id='ctrl-1',
            payload={'cmd': 'rebuild'},
            reason='transient error',
        )
        self.assertIsNotNone(task.id)
        self.assertEqual(task.controller_id, 'ctrl-1')
        self.assertEqual(task.payload, {'cmd': 'rebuild'})
        self.assertEqual(task.reason, 'transient error')
        self.assertEqual(task.attempts, 0)
        self.assertEqual(task.max_attempts, 3)

    async def test_schedule_with_metadata(self):
        task = await self.queue.schedule(
            controller_id='ctrl-1',
            payload={},
            reason='test',
            metadata={'priority': 'high'},
        )
        self.assertEqual(task.metadata, {'priority': 'high'})

    async def test_schedule_with_custom_max_attempts(self):
        task = await self.queue.schedule(
            controller_id='ctrl-1',
            payload={},
            reason='test',
            max_attempts=10,
        )
        self.assertEqual(task.max_attempts, 10)

    async def test_schedule_with_initial_delay(self):
        before = time.time()
        task = await self.queue.schedule(
            controller_id='ctrl-1',
            payload={},
            reason='test',
            initial_delay=5.0,
        )
        self.assertGreaterEqual(task.next_attempt_at, before + 5.0)

    async def test_fetch_ready_delegates(self):
        await self.queue.schedule(
            controller_id='ctrl-1',
            payload={},
            reason='test',
            initial_delay=0,
        )
        # Task should be ready immediately (initial_delay=0 → time.time() + 0)
        # Need to wait for time to pass due to scheduling at time.time()
        ready = await self.queue.fetch_ready('ctrl-1', 5)
        self.assertEqual(len(ready), 1)

    async def test_mark_success_delegates(self):
        await self.queue.schedule(
            controller_id='ctrl-1',
            payload={},
            reason='test',
            initial_delay=0,
        )
        ready = await self.queue.fetch_ready('ctrl-1', 1)
        self.assertEqual(len(ready), 1)
        await self.queue.mark_success(ready[0])
        # Task should be removed
        remaining = await self.queue.fetch_ready('ctrl-1', 5)
        self.assertEqual(len(remaining), 0)

    async def test_mark_failure_reschedules(self):
        await self.queue.schedule(
            controller_id='ctrl-1',
            payload={},
            reason='test',
            initial_delay=0,
        )
        ready = await self.queue.fetch_ready('ctrl-1', 1)
        result = await self.queue.mark_failure(
            ready[0], error_message='connection refused'
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.reason, 'connection refused')

    async def test_mark_failure_exhausted(self):
        await self.queue.schedule(
            controller_id='ctrl-1',
            payload={},
            reason='test',
            initial_delay=0,
            max_attempts=1,
        )
        ready = await self.queue.fetch_ready('ctrl-1', 1)
        # After fetch, attempts = 1, max_attempts = 1 → exhausted
        result = await self.queue.mark_failure(
            ready[0], error_message='permanent error'
        )
        self.assertIsNone(result)

    async def test_dead_letter_delegates(self):
        task = await self.queue.schedule(
            controller_id='ctrl-1',
            payload={},
            reason='test',
        )
        await self.queue.dead_letter(task)
        self.assertEqual(len(self.backend._dead_letter), 1)

    def test_compute_backoff_base(self):
        # attempts=1 → base_delay * 2^0 = 1.0
        self.assertEqual(self.queue._compute_backoff(1), 1.0)

    def test_compute_backoff_exponential(self):
        # attempts=2 → 1.0 * 2^1 = 2.0
        self.assertEqual(self.queue._compute_backoff(2), 2.0)
        # attempts=3 → 1.0 * 2^2 = 4.0
        self.assertEqual(self.queue._compute_backoff(3), 4.0)

    def test_compute_backoff_capped(self):
        # attempts=10 → 1.0 * 2^9 = 512.0, capped at max_delay=60.0
        self.assertEqual(self.queue._compute_backoff(10), 60.0)

    def test_compute_backoff_zero_attempts(self):
        # attempts=0 → treated as 1 → base_delay * 2^0 = 1.0
        self.assertEqual(self.queue._compute_backoff(0), 1.0)


class TestGetRetryQueue(unittest.TestCase):
    """Tests for get_retry_queue singleton factory."""

    def setUp(self):
        # Reset singleton before each test
        import backend.core.retry_queue as rq_module

        rq_module._retry_queue = None

    def tearDown(self):
        import backend.core.retry_queue as rq_module

        rq_module._retry_queue = None

    def test_returns_none_when_disabled(self):
        with patch.dict('os.environ', {'RETRY_QUEUE_ENABLED': 'false'}, clear=False):
            result = get_retry_queue()
            self.assertIsNone(result)

    def test_returns_queue_when_enabled(self):
        with patch.dict(
            'os.environ',
            {
                'RETRY_QUEUE_ENABLED': 'true',
                'RETRY_QUEUE_BACKEND': 'memory',
            },
            clear=False,
        ):
            result = get_retry_queue()
            self.assertIsNotNone(result)
            assert result is not None
            self.assertIsInstance(result, RetryQueue)
            self.assertIsInstance(result.backend, InMemoryRetryBackend)

    def test_returns_cached_singleton(self):
        with patch.dict(
            'os.environ',
            {
                'RETRY_QUEUE_ENABLED': 'true',
                'RETRY_QUEUE_BACKEND': 'memory',
            },
            clear=False,
        ):
            q1 = get_retry_queue()
            q2 = get_retry_queue()
            self.assertIs(q1, q2)

    def test_custom_config_from_env(self):
        with patch.dict(
            'os.environ',
            {
                'RETRY_QUEUE_ENABLED': 'true',
                'RETRY_QUEUE_BACKEND': 'memory',
                'RETRY_QUEUE_RETRY_DELAY_SECONDS': '30.0',
                'RETRY_QUEUE_MAX_DELAY_SECONDS': '1800.0',
                'RETRY_QUEUE_MAX_RETRIES': '5',
                'RETRY_QUEUE_POLL_INTERVAL': '10.0',
            },
            clear=False,
        ):
            q = get_retry_queue()
            assert q is not None
            self.assertEqual(q.base_delay, 30.0)
            self.assertEqual(q.max_delay, 1800.0)
            self.assertEqual(q.max_retries, 5)
            self.assertEqual(q.poll_interval, 10.0)

    def test_disabled_values(self):
        for val in ('false', '0', 'no', 'anything'):
            import backend.core.retry_queue as rq_module

            rq_module._retry_queue = None
            with patch.dict('os.environ', {'RETRY_QUEUE_ENABLED': val}, clear=False):
                result = get_retry_queue()
                self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main()
