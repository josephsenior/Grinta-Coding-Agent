"""Unit tests for backend.core.retry_queue — in-memory retry backend & queue."""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.retry_queue import (
    InMemoryRetryBackend,
    RedisRetryBackend,
    RetryQueue,
    RetryTask,
    get_retry_queue,
)


# ---------------------------------------------------------------------------
# RetryTask dataclass
# ---------------------------------------------------------------------------


class TestRetryTask:
    def test_defaults(self):
        t = RetryTask(id="t1", controller_id="c1", payload={"x": 1}, reason="err")
        assert t.attempts == 0
        assert t.max_attempts == 3
        assert t.last_error is None

    def test_to_dict(self):
        t = RetryTask(id="t1", controller_id="c1", payload={"x": 1}, reason="err")
        d = t.to_dict()
        assert d["id"] == "t1"
        assert d["controller_id"] == "c1"
        assert d["payload"] == {"x": 1}

    def test_roundtrip(self):
        t = RetryTask(
            id="t1", controller_id="c1", payload={"y": 2}, reason="retry",
            attempts=2, max_attempts=5, metadata={"k": "v"},
        )
        d = t.to_dict()
        t2 = RetryTask.from_dict(d)
        assert t2.id == t.id
        assert t2.attempts == 2
        assert t2.metadata == {"k": "v"}

    def test_from_dict_defaults(self):
        d = {"id": "t1", "controller_id": "c1"}
        t = RetryTask.from_dict(d)
        assert t.payload == {}
        assert t.reason == ""
        assert t.attempts == 0


# ---------------------------------------------------------------------------
# InMemoryRetryBackend
# ---------------------------------------------------------------------------


class TestInMemoryRetryBackend:
    @pytest.mark.asyncio
    async def test_schedule_and_fetch(self):
        b = InMemoryRetryBackend()
        task = RetryTask(
            id="t1", controller_id="c1", payload={}, reason="test",
            next_attempt_at=time.time() - 1,  # already ready
        )
        await b.schedule(task)
        ready = await b.fetch_ready("c1", limit=5)
        assert len(ready) == 1
        assert ready[0].id == "t1"
        assert ready[0].attempts == 1  # incremented on fetch

    @pytest.mark.asyncio
    async def test_fetch_not_ready_yet(self):
        b = InMemoryRetryBackend()
        task = RetryTask(
            id="t1", controller_id="c1", payload={}, reason="test",
            next_attempt_at=time.time() + 9999,
        )
        await b.schedule(task)
        ready = await b.fetch_ready("c1", limit=5)
        assert len(ready) == 0

    @pytest.mark.asyncio
    async def test_fetch_wrong_controller(self):
        b = InMemoryRetryBackend()
        task = RetryTask(
            id="t1", controller_id="c1", payload={}, reason="test",
            next_attempt_at=time.time() - 1,
        )
        await b.schedule(task)
        ready = await b.fetch_ready("c2", limit=5)
        assert len(ready) == 0

    @pytest.mark.asyncio
    async def test_mark_success(self):
        b = InMemoryRetryBackend()
        task = RetryTask(id="t1", controller_id="c1", payload={}, reason="test")
        await b.schedule(task)
        await b.mark_success(task)
        assert "t1" not in b._tasks

    @pytest.mark.asyncio
    async def test_mark_failure_requeues(self):
        b = InMemoryRetryBackend()
        task = RetryTask(
            id="t1", controller_id="c1", payload={}, reason="test",
            attempts=1, max_attempts=3,
        )
        await b.schedule(task)
        result = await b.mark_failure(task, backoff_seconds=0.0)
        assert result is not None
        assert result.id == "t1"

    @pytest.mark.asyncio
    async def test_mark_failure_dead_letters(self):
        b = InMemoryRetryBackend()
        task = RetryTask(
            id="t1", controller_id="c1", payload={}, reason="test",
            attempts=3, max_attempts=3,
        )
        await b.schedule(task)
        result = await b.mark_failure(task, backoff_seconds=0.0)
        assert result is None
        assert len(b._dead_letter) == 1

    @pytest.mark.asyncio
    async def test_dead_letter_explicit(self):
        b = InMemoryRetryBackend()
        task = RetryTask(id="t1", controller_id="c1", payload={}, reason="test")
        await b.schedule(task)
        await b.dead_letter(task)
        assert len(b._dead_letter) == 1
        assert "t1" not in b._tasks


# ---------------------------------------------------------------------------
# RetryQueue (high-level wrapper)
# ---------------------------------------------------------------------------


class TestRetryQueue:
    def _make_queue(self, **kwargs) -> RetryQueue:
        defaults = {
            "backend": InMemoryRetryBackend(),
            "base_delay": 1.0,
            "max_delay": 60.0,
            "max_retries": 3,
            "poll_interval": 1.0,
        }
        defaults.update(kwargs)
        return RetryQueue(**defaults)

    @pytest.mark.asyncio
    async def test_schedule(self):
        q = self._make_queue()
        task = await q.schedule("c1", {"data": 1}, reason="err")
        assert task.controller_id == "c1"
        assert task.reason == "err"

    @pytest.mark.asyncio
    async def test_schedule_custom_attempts(self):
        q = self._make_queue()
        task = await q.schedule("c1", {}, reason="err", max_attempts=5)
        assert task.max_attempts == 5

    @pytest.mark.asyncio
    async def test_mark_success(self):
        q = self._make_queue()
        await q.schedule("c1", {}, reason="err", initial_delay=0)
        ready = await q.fetch_ready("c1", limit=1)
        assert len(ready) == 1
        await q.mark_success(ready[0])

    @pytest.mark.asyncio
    async def test_mark_failure_requeues(self):
        q = self._make_queue()
        task = RetryTask(
            id="t1", controller_id="c1", payload={}, reason="test",
            attempts=1, max_attempts=3,
        )
        await q.backend.schedule(task)
        result = await q.mark_failure(task, error_message="some err")
        assert result is not None

    def test_compute_backoff(self):
        q = self._make_queue(base_delay=2.0, max_delay=16.0)
        assert q._compute_backoff(1) == 2.0  # 2 * 2^0
        assert q._compute_backoff(2) == 4.0  # 2 * 2^1
        assert q._compute_backoff(3) == 8.0  # 2 * 2^2
        assert q._compute_backoff(4) == 16.0  # 2 * 2^3
        assert q._compute_backoff(10) == 16.0  # capped

    def test_compute_backoff_zero_attempts(self):
        q = self._make_queue(base_delay=1.0)
        assert q._compute_backoff(0) == 1.0  # max(0,1) = 1 → 1*2^0 = 1


class TestRedisRetryBackend:
    def _make_backend(self):
        import backend.core.retry_queue as rq

        client = MagicMock()
        client.zpopmin = AsyncMock(return_value=[])
        client.zadd = AsyncMock()
        client.hget = AsyncMock(return_value=None)
        client.hdel = AsyncMock()
        client.pipeline = MagicMock()

        class FakePipeline:
            def __init__(self):
                self.calls = []

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            def hset(self, *args, **kwargs):
                self.calls.append(("hset", args, kwargs))
                return self

            def zadd(self, *args, **kwargs):
                self.calls.append(("zadd", args, kwargs))
                return self

            def hdel(self, *args, **kwargs):
                self.calls.append(("hdel", args, kwargs))
                return self

            def lpush(self, *args, **kwargs):
                self.calls.append(("lpush", args, kwargs))
                return self

            async def execute(self):
                return True

        client.pipeline.return_value = FakePipeline()

        fake_redis = MagicMock()
        fake_redis.ConnectionPool.from_url.return_value = "pool"
        fake_redis.Redis.return_value = client

        rq.REDIS_AVAILABLE = True
        rq.redis = fake_redis

        backend = RedisRetryBackend("redis://localhost:6379")
        return backend, client, client.pipeline.return_value

    @pytest.mark.asyncio
    async def test_schedule(self):
        backend, _client, pipe = self._make_backend()
        task = RetryTask(id="t1", controller_id="c1", payload={}, reason="x")
        await backend.schedule(task)
        assert any(call[0] == "hset" for call in pipe.calls)
        assert any(call[0] == "zadd" for call in pipe.calls)

    @pytest.mark.asyncio
    async def test_fetch_ready_requeues_future(self):
        backend, client, _pipe = self._make_backend()
        future_time = time.time() + 100
        client.zpopmin = AsyncMock(return_value=[("t1", future_time)])
        client.zadd = AsyncMock()

        ready = await backend.fetch_ready("c1", limit=1)
        assert ready == []
        client.zadd.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_fetch_ready_returns_task(self):
        backend, client, _pipe = self._make_backend()
        now = time.time() - 1
        task = RetryTask(id="t1", controller_id="c1", payload={}, reason="x")
        client.zpopmin = AsyncMock(return_value=[("t1", now)])
        client.hget = AsyncMock(return_value=json.dumps(task.to_dict()))

        ready = await backend.fetch_ready("c1", limit=1)
        assert len(ready) == 1
        assert ready[0].attempts == 1

    @pytest.mark.asyncio
    async def test_mark_success(self):
        backend, client, _pipe = self._make_backend()
        task = RetryTask(id="t1", controller_id="c1", payload={}, reason="x")
        await backend.mark_success(task)
        client.hdel.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_mark_failure_requeues(self):
        backend, client, pipe = self._make_backend()
        task = RetryTask(
            id="t1", controller_id="c1", payload={}, reason="x", attempts=1, max_attempts=3
        )
        result = await backend.mark_failure(task, backoff_seconds=1.0)
        assert result is not None
        assert any(call[0] == "hset" for call in pipe.calls)
        assert any(call[0] == "zadd" for call in pipe.calls)

    @pytest.mark.asyncio
    async def test_mark_failure_dead_letters(self):
        backend, _client, _pipe = self._make_backend()
        task = RetryTask(
            id="t1", controller_id="c1", payload={}, reason="x", attempts=3, max_attempts=3
        )
        backend.dead_letter = AsyncMock()
        result = await backend.mark_failure(task, backoff_seconds=1.0)
        assert result is None
        backend.dead_letter.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_dead_letter(self):
        backend, _client, pipe = self._make_backend()
        task = RetryTask(id="t1", controller_id="c1", payload={}, reason="x")
        await backend.dead_letter(task)
        assert any(call[0] == "hdel" for call in pipe.calls)
        assert any(call[0] == "lpush" for call in pipe.calls)


class TestGetRetryQueue:
    def test_disabled_returns_none(self, monkeypatch):
        monkeypatch.setenv("RETRY_QUEUE_ENABLED", "false")
        import backend.core.retry_queue as rq

        rq._retry_queue = None
        assert get_retry_queue() is None

    def test_existing_singleton(self, monkeypatch):
        monkeypatch.setenv("RETRY_QUEUE_ENABLED", "true")
        import backend.core.retry_queue as rq

        rq._retry_queue = RetryQueue(
            backend=InMemoryRetryBackend(),
            base_delay=1.0,
            max_delay=10.0,
            max_retries=3,
            poll_interval=1.0,
        )
        assert get_retry_queue() is rq._retry_queue

    def test_forces_memory_backend_when_pytest(self, monkeypatch):
        monkeypatch.setenv("RETRY_QUEUE_ENABLED", "true")
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "x")
        monkeypatch.delenv("RETRY_QUEUE_BACKEND", raising=False)
        import backend.core.retry_queue as rq

        rq._retry_queue = None
        queue = get_retry_queue()
        assert isinstance(queue.backend, InMemoryRetryBackend)

    def test_redis_backend_selected(self, monkeypatch):
        monkeypatch.setenv("RETRY_QUEUE_ENABLED", "true")
        monkeypatch.setenv("RETRY_QUEUE_BACKEND", "redis")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")

        import backend.core.retry_queue as rq

        rq._retry_queue = None
        rq.REDIS_AVAILABLE = True

        with patch("backend.core.retry_queue.RedisRetryBackend") as backend_cls:
            backend_cls.return_value = MagicMock()
            queue = get_retry_queue()

        assert queue is not None
        backend_cls.assert_called_once()
