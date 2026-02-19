"""Persistent retry queue with Redis backend and in-memory fallback."""

from __future__ import annotations

import asyncio
import heapq
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from backend.core.logger import forge_logger as logger

try:  # pragma: no cover - optional dependency
    import redis.asyncio as redis

    redis_available = True
except ImportError:  # pragma: no cover - skip redis backend when unavailable
    redis = None  # type: ignore
    redis_available = False


@dataclass
class RetryTask:
    """Represents a scheduled retry operation."""

    id: str
    controller_id: str
    payload: dict[str, Any]
    reason: str
    attempts: int = 0
    max_attempts: int = 3
    next_attempt_at: float = field(default_factory=time.time)
    created_at: float = field(default_factory=time.time)
    last_error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize retry task to dictionary."""
        return {
            "id": self.id,
            "controller_id": self.controller_id,
            "payload": self.payload,
            "reason": self.reason,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "next_attempt_at": self.next_attempt_at,
            "created_at": self.created_at,
            "last_error": self.last_error,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RetryTask:
        """Deserialize retry task from dictionary."""
        return cls(
            id=data["id"],
            controller_id=data["controller_id"],
            payload=data.get("payload", {}),
            reason=data.get("reason", ""),
            attempts=int(data.get("attempts", 0)),
            max_attempts=int(data.get("max_attempts", 3)),
            next_attempt_at=float(data.get("next_attempt_at", time.time())),
            created_at=float(data.get("created_at", time.time())),
            last_error=data.get("last_error"),
            metadata=data.get("metadata", {}),
        )


class BaseRetryBackend:
    """Abstract backend API."""

    async def schedule(self, task: RetryTask) -> RetryTask:
        raise NotImplementedError

    async def fetch_ready(self, controller_id: str, limit: int) -> list[RetryTask]:
        raise NotImplementedError

    async def mark_success(self, task: RetryTask) -> None:
        raise NotImplementedError

    async def mark_failure(
        self, task: RetryTask, backoff_seconds: float
    ) -> RetryTask | None:
        raise NotImplementedError

    async def dead_letter(self, task: RetryTask) -> None:
        raise NotImplementedError


class InMemoryRetryBackend(BaseRetryBackend):
    """In-memory retry backend with heap-based scheduling."""

    def __init__(self) -> None:
        self._tasks: dict[str, RetryTask] = {}
        self._heap: list[tuple[float, str]] = []
        self._lock = asyncio.Lock()
        self._dead_letter: list[RetryTask] = []

    async def schedule(self, task: RetryTask) -> RetryTask:
        async with self._lock:
            self._tasks[task.id] = task
            heapq.heappush(self._heap, (task.next_attempt_at, task.id))
        logger.debug("Scheduled retry task %s (attempts=%s)", task.id, task.attempts)
        return task

    async def fetch_ready(self, controller_id: str, limit: int) -> list[RetryTask]:
        ready: list[RetryTask] = []
        now = time.time()
        async with self._lock:
            while self._heap and len(ready) < limit:
                next_time, task_id = heapq.heappop(self._heap)
                task = self._tasks.get(task_id)
                if task is None:
                    continue
                if task.controller_id != controller_id:
                    # Not for this controller, push back
                    heapq.heappush(self._heap, (next_time, task_id))
                    break
                if next_time > now:
                    # Not ready yet, requeue and break
                    heapq.heappush(self._heap, (next_time, task_id))
                    break
                task.attempts += 1
                ready.append(task)
        return ready

    async def mark_success(self, task: RetryTask) -> None:
        async with self._lock:
            self._tasks.pop(task.id, None)
        logger.debug("Retry task %s succeeded, removed from queue", task.id)

    async def mark_failure(
        self, task: RetryTask, backoff_seconds: float
    ) -> RetryTask | None:
        async with self._lock:
            task.last_error = task.reason
            if task.attempts >= task.max_attempts:
                self._dead_letter.append(task)
                self._tasks.pop(task.id, None)
                logger.warning(
                    "Retry task %s exceeded max attempts (%s)",
                    task.id,
                    task.max_attempts,
                )
                return None
            task.next_attempt_at = time.time() + backoff_seconds
            self._tasks[task.id] = task
            heapq.heappush(self._heap, (task.next_attempt_at, task.id))
            logger.info(
                "Retry task %s scheduled again in %.1fs (attempt %s/%s)",
                task.id,
                backoff_seconds,
                task.attempts,
                task.max_attempts,
            )
            return task

    async def dead_letter(self, task: RetryTask) -> None:
        async with self._lock:
            self._dead_letter.append(task)
            self._tasks.pop(task.id, None)
        logger.error("Retry task %s moved to dead letter queue", task.id)


class RedisRetryBackend(BaseRetryBackend):
    """Redis-backed retry queue for distributed environments."""

    def __init__(
        self,
        redis_url: str,
        pool_size: int = 10,
        connection_timeout: float = 5.0,
    ) -> None:
        if not redis_available:
            raise RuntimeError("redis.asyncio is required for RedisRetryBackend")
        self.redis_url = redis_url
        self._pool = redis.ConnectionPool.from_url(
            redis_url,
            max_connections=pool_size,
            decode_responses=True,
            socket_connect_timeout=connection_timeout,
            socket_timeout=connection_timeout,
            retry_on_timeout=True,
            health_check_interval=30,
        )
        self._client = redis.Redis(connection_pool=self._pool)

    def _schedule_key(self, controller_id: str) -> str:
        return f"retry_queue:{controller_id}:schedule"

    def _tasks_key(self, controller_id: str) -> str:
        return f"retry_queue:{controller_id}:tasks"

    def _dead_letter_key(self, controller_id: str) -> str:
        return f"retry_queue:{controller_id}:dead_letter"

    async def schedule(self, task: RetryTask) -> RetryTask:
        tasks_key = self._tasks_key(task.controller_id)
        schedule_key = self._schedule_key(task.controller_id)
        payload = json.dumps(task.to_dict())
        async with self._client.pipeline() as pipe:
            pipe.hset(tasks_key, task.id, payload)
            pipe.zadd(schedule_key, {task.id: task.next_attempt_at})
            await pipe.execute()
        logger.debug(
            "Scheduled retry task %s for controller %s (next_at=%.2f)",
            task.id,
            task.controller_id,
            task.next_attempt_at,
        )
        return task

    async def fetch_ready(self, controller_id: str, limit: int) -> list[RetryTask]:
        schedule_key = self._schedule_key(controller_id)
        tasks_key = self._tasks_key(controller_id)
        ready: list[RetryTask] = []
        now = time.time()

        for _ in range(limit):
            popped = await self._client.zpopmin(schedule_key)
            if not popped:
                break
            task_id, score = popped[0]
            if score > now:
                # Not ready yet; requeue and stop fetching
                await self._client.zadd(schedule_key, {task_id: score})
                break
            task_json = await self._client.hget(tasks_key, task_id)
            if not task_json:
                continue
            task_dict = json.loads(task_json)
            task = RetryTask.from_dict(task_dict)
            task.attempts += 1
            ready.append(task)
        return ready

    async def mark_success(self, task: RetryTask) -> None:
        tasks_key = self._tasks_key(task.controller_id)
        await self._client.hdel(tasks_key, task.id)
        logger.debug(
            "Retry task %s acknowledged by controller %s", task.id, task.controller_id
        )

    async def mark_failure(
        self, task: RetryTask, backoff_seconds: float
    ) -> RetryTask | None:
        tasks_key = self._tasks_key(task.controller_id)
        schedule_key = self._schedule_key(task.controller_id)
        if task.attempts >= task.max_attempts:
            await self.dead_letter(task)
            return None

        task.next_attempt_at = time.time() + backoff_seconds
        task_dict = task.to_dict()
        payload = json.dumps(task_dict)
        async with self._client.pipeline() as pipe:
            pipe.hset(tasks_key, task.id, payload)
            pipe.zadd(schedule_key, {task.id: task.next_attempt_at})
            await pipe.execute()
        logger.info(
            "Retry task %s requeued for controller %s in %.1fs (attempt %s/%s)",
            task.id,
            task.controller_id,
            backoff_seconds,
            task.attempts,
            task.max_attempts,
        )
        return task

    async def dead_letter(self, task: RetryTask) -> None:
        tasks_key = self._tasks_key(task.controller_id)
        dead_key = self._dead_letter_key(task.controller_id)
        payload = json.dumps(task.to_dict())
        async with self._client.pipeline() as pipe:
            pipe.hdel(tasks_key, task.id)
            pipe.lpush(dead_key, payload)
            await pipe.execute()
        logger.error(
            "Retry task %s moved to dead letter queue for controller %s",
            task.id,
            task.controller_id,
        )


class RetryQueue:
    """High-level retry queue wrapper with automatic backend selection."""

    def __init__(
        self,
        backend: BaseRetryBackend,
        *,
        base_delay: float,
        max_delay: float,
        max_retries: int,
        poll_interval: float,
    ) -> None:
        self.backend = backend
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.max_retries = max_retries
        self.poll_interval = poll_interval

    async def schedule(
        self,
        controller_id: str,
        payload: dict[str, Any],
        *,
        reason: str,
        metadata: dict[str, Any] | None = None,
        initial_delay: float | None = None,
        max_attempts: int | None = None,
    ) -> RetryTask:
        task_id = str(uuid.uuid4())
        delay = initial_delay if initial_delay is not None else self.base_delay
        next_attempt = time.time() + max(delay, 0.0)
        task = RetryTask(
            id=task_id,
            controller_id=controller_id,
            payload=payload,
            reason=reason,
            attempts=0,
            max_attempts=max_attempts or self.max_retries,
            next_attempt_at=next_attempt,
            metadata=metadata or {},
        )
        return await self.backend.schedule(task)

    async def fetch_ready(self, controller_id: str, limit: int = 1) -> list[RetryTask]:
        return await self.backend.fetch_ready(controller_id, limit)

    async def mark_success(self, task: RetryTask) -> None:
        await self.backend.mark_success(task)

    async def mark_failure(
        self, task: RetryTask, *, error_message: str
    ) -> RetryTask | None:
        task.reason = error_message
        backoff_seconds = self._compute_backoff(task.attempts)
        return await self.backend.mark_failure(task, backoff_seconds)

    async def dead_letter(self, task: RetryTask) -> None:
        await self.backend.dead_letter(task)

    def _compute_backoff(self, attempts: int) -> float:
        attempts = max(attempts, 1)
        delay = self.base_delay * (2 ** (attempts - 1))
        return min(delay, self.max_delay)


_retry_queue: RetryQueue | None = None


def get_retry_queue() -> RetryQueue | None:
    """Return singleton retry queue if enabled."""
    global _retry_queue
    if _retry_queue is not None:
        return _retry_queue

    enabled = os.getenv("RETRY_QUEUE_ENABLED", "true").lower() in ("true", "1", "yes")
    if not enabled:
        return None

    # Prefer in-memory backend when running under pytest to avoid Redis noise
    is_pytest = os.getenv("PYTEST_CURRENT_TEST") is not None or os.getenv(
        "PYTEST_RUNNING", ""
    ).lower() in (
        "1",
        "true",
        "yes",
    )
    default_backend = "memory" if is_pytest else "redis"
    backend_name = os.getenv("RETRY_QUEUE_BACKEND", default_backend).lower()
    base_delay = float(os.getenv("RETRY_QUEUE_RETRY_DELAY_SECONDS", "60.0"))
    max_delay = float(os.getenv("RETRY_QUEUE_MAX_DELAY_SECONDS", "3600.0"))
    max_retries = int(os.getenv("RETRY_QUEUE_MAX_RETRIES", "3"))
    poll_interval = float(os.getenv("RETRY_QUEUE_POLL_INTERVAL", "5.0"))

    backend: BaseRetryBackend
    if backend_name == "redis" and redis_available:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        pool_size = int(os.getenv("REDIS_POOL_SIZE", "10"))
        timeout = float(os.getenv("REDIS_TIMEOUT", "5.0"))
        try:
            backend = RedisRetryBackend(
                redis_url, pool_size=pool_size, connection_timeout=timeout
            )
            logger.info("RetryQueue configured with Redis backend (%s)", redis_url)
        except Exception as exc:  # pragma: no cover - fallback path
            logger.warning(
                "Failed to initialize Redis retry backend: %s. Falling back to in-memory.",
                exc,
            )
            backend = InMemoryRetryBackend()
    else:
        backend = InMemoryRetryBackend()
        logger.info("RetryQueue using in-memory backend")

    _retry_queue = RetryQueue(
        backend,
        base_delay=base_delay,
        max_delay=max_delay,
        max_retries=max_retries,
        poll_interval=poll_interval,
    )
    return _retry_queue
