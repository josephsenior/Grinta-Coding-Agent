"""Unit tests for backend.core.retry_queue — in-memory retry backend & queue."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

import pytest

from backend.core.retry_queue import (
    InMemoryRetryBackend,
    RetryQueue,
    RetryTask,
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
        defaults = dict(
            backend=InMemoryRetryBackend(),
            base_delay=1.0,
            max_delay=60.0,
            max_retries=3,
            poll_interval=1.0,
        )
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
        task = await q.schedule("c1", {}, reason="err", initial_delay=0)
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
