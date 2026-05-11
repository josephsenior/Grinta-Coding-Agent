"""Autonomous recovery retry queue with an in-memory backend.

Scheduled retry metadata is process-local by design. If the CLI process exits
or crashes before a retry fires, pending retry metadata is lost and the next run
resumes from the durable event/session state instead.

A lightweight JSON sidecar file is written to session storage on every
``schedule()`` and removed on ``mark_success()`` / ``mark_failure()`` (when
the task is removed). On startup, ``recover_pending()`` can be called to
re-inject tasks that were in-flight at crash time.
"""

from __future__ import annotations

import asyncio
import heapq
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.core.logger import app_logger as logger


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
            'id': self.id,
            'controller_id': self.controller_id,
            'payload': self.payload,
            'reason': self.reason,
            'attempts': self.attempts,
            'max_attempts': self.max_attempts,
            'next_attempt_at': self.next_attempt_at,
            'created_at': self.created_at,
            'last_error': self.last_error,
            'metadata': self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RetryTask:
        """Deserialize retry task from dictionary."""
        return cls(
            id=data['id'],
            controller_id=data['controller_id'],
            payload=data.get('payload', {}),
            reason=data.get('reason', ''),
            attempts=int(data.get('attempts', 0)),
            max_attempts=int(data.get('max_attempts', 3)),
            next_attempt_at=float(data.get('next_attempt_at', time.time())),
            created_at=float(data.get('created_at', time.time())),
            last_error=data.get('last_error'),
            metadata=data.get('metadata', {}),
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
    """In-memory retry backend with heap-based scheduling and optional sidecar persistence."""

    def __init__(self, persist_dir: str | Path | None = None) -> None:
        self._tasks: dict[str, RetryTask] = {}
        self._heap: list[tuple[float, str]] = []
        self._lock = asyncio.Lock()
        self._dead_letter: list[RetryTask] = []
        self._persist_dir = Path(persist_dir) if persist_dir else None
        if self._persist_dir:
            self._persist_dir.mkdir(parents=True, exist_ok=True)

    def _sidecar_path(self, task_id: str) -> Path | None:
        if self._persist_dir is None:
            return None
        return self._persist_dir / f'retry_{task_id}.json'

    def _write_sidecar(self, task: RetryTask) -> None:
        path = self._sidecar_path(task.id)
        if path is None:
            return
        try:
            path.write_text(json.dumps(task.to_dict()), encoding='utf-8')
        except Exception:
            logger.debug('Retry sidecar write failed for %s', task.id, exc_info=True)

    def _remove_sidecar(self, task_id: str) -> None:
        path = self._sidecar_path(task_id)
        if path is None:
            return
        try:
            path.unlink(missing_ok=True)
        except Exception:
            logger.debug('Retry sidecar remove failed for %s', task_id, exc_info=True)

    async def schedule(self, task: RetryTask) -> RetryTask:
        async with self._lock:
            self._tasks[task.id] = task
            heapq.heappush(self._heap, (task.next_attempt_at, task.id))
        self._write_sidecar(task)
        logger.debug('Scheduled retry task %s (attempts=%s)', task.id, task.attempts)
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
        self._remove_sidecar(task.id)
        logger.debug('Retry task %s succeeded, removed from queue', task.id)

    async def mark_failure(
        self, task: RetryTask, backoff_seconds: float
    ) -> RetryTask | None:
        async with self._lock:
            task.last_error = task.reason
            if task.attempts >= task.max_attempts:
                self._dead_letter.append(task)
                self._tasks.pop(task.id, None)
                logger.warning(
                    'Retry task %s exceeded max attempts (%s)',
                    task.id,
                    task.max_attempts,
                )
                self._remove_sidecar(task.id)
                return None
            task.next_attempt_at = time.time() + backoff_seconds
            self._tasks[task.id] = task
            heapq.heappush(self._heap, (task.next_attempt_at, task.id))
            self._write_sidecar(task)
            logger.info(
                'Retry task %s scheduled again in %.1fs (attempt %s/%s)',
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
        self._remove_sidecar(task.id)
        logger.error('Retry task %s moved to dead letter queue', task.id)

    def recover_pending(self) -> list[RetryTask]:
        """Re-cover sidecar tasks left over from a previous process crash.

        Scans ``persist_dir`` for ``retry_*.json`` files and loads any
        tasks whose ``next_attempt_at`` is still in the future.  Tasks
        whose next attempt has already passed are placed in the dead
        letter queue to avoid replaying stale retries.

        Returns the list of recovered tasks for diagnostic logging.
        """
        if self._persist_dir is None:
            return []
        recovered: list[RetryTask] = []
        try:
            for path in self._persist_dir.glob('retry_*.json'):
                try:
                    data = json.loads(path.read_text(encoding='utf-8'))
                    task = RetryTask.from_dict(data)
                except Exception:
                    logger.debug('Retry sidecar corrupt: %s', path, exc_info=True)
                    continue
                if task.next_attempt_at <= time.time():
                    self._dead_letter.append(task)
                    self._remove_sidecar(task.id)
                    logger.info('Retry sidecar expired, moved to dead letter: %s', task.id)
                else:
                    self._tasks[task.id] = task
                    heapq.heappush(self._heap, (task.next_attempt_at, task.id))
                    recovered.append(task)
                    logger.info('Retry sidecar recovered: %s', task.id)
        except Exception:
            logger.debug('Retry sidecar scan failed', exc_info=True)
        return recovered


class RetryQueue:
    """High-level process-local retry queue wrapper."""

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

    enabled = os.getenv('RETRY_QUEUE_ENABLED', 'true').lower() in ('true', '1', 'yes')
    if not enabled:
        return None

    backend_name = os.getenv('RETRY_QUEUE_BACKEND', 'memory').lower()
    base_delay = float(os.getenv('RETRY_QUEUE_RETRY_DELAY_SECONDS', '10.0'))
    max_delay = float(os.getenv('RETRY_QUEUE_MAX_DELAY_SECONDS', '120.0'))
    # Generous default: the system is autonomous, so prefer many quiet retries
    # over surfacing transient infrastructure errors to the agent. Combined
    # with the inner Tenacity loop (DEFAULT_LLM_NUM_RETRIES = 5, plus the
    # provider-hint bonus), this yields ~25 underlying attempts before the
    # agent ever sees a rate-limit failure. See ``recovery_service`` for the
    # context-suppression policy.
    max_retries = int(os.getenv('RETRY_QUEUE_MAX_RETRIES', '5'))
    poll_interval = float(os.getenv('RETRY_QUEUE_POLL_INTERVAL', '5.0'))

    if backend_name not in ('', 'memory'):
        logger.warning(
            'RetryQueue backend %s is no longer supported; retry metadata is process-local',
            backend_name,
        )

    backend: BaseRetryBackend = InMemoryRetryBackend(
        persist_dir=os.getenv('RETRY_QUEUE_PERSIST_DIR') or None
    )
    logger.info('RetryQueue using process-local in-memory backend')

    _retry_queue = RetryQueue(
        backend,
        base_delay=base_delay,
        max_delay=max_delay,
        max_retries=max_retries,
        poll_interval=poll_interval,
    )
    return _retry_queue
