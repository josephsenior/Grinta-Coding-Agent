"""Process shutdown coordination for long-running loops.

Uvicorn (and other ASGI servers) install SIGINT/SIGTERM handlers and run FastAPI
lifespan shutdown. This module does **not** register signal handlers — that
avoided fighting the server and broken Ctrl+C on Windows.

Callers that need to stop background work should use :func:`should_continue` /
:func:`should_exit`. The API lifespan calls :func:`backend.gateway.graceful_shutdown`
which invokes :func:`request_process_shutdown` so those loops unwind cleanly.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from uuid import UUID, uuid4

from backend.core.logger import app_logger as logger

# True once graceful shutdown has been requested for this process.
_should_exit: bool = False
# Incremented on each lifespan reset so stale background tasks can detect staleness.
_lifecycle_generation: int = 0
_shutdown_listeners: dict[UUID, Callable[[], None]] = {}


def request_process_shutdown() -> None:
    """Mark the process as shutting down and notify registered listeners once.

    Idempotent. Safe to call from the main thread during ASGI lifespan shutdown.
    """
    global _should_exit
    if _should_exit:
        return
    _should_exit = True
    for listener in list(_shutdown_listeners.values()):
        try:
            listener()
        except Exception:
            logger.exception("Error in shutdown listener")


def should_exit() -> bool:
    """Return True when the application should stop long-running work."""
    return _should_exit


def should_continue() -> bool:
    """Return False when background loops should exit."""
    return not _should_exit


def get_lifecycle_generation() -> int:
    """Return the current lifecycle generation.

    Background loops can snapshot this at startup and call
    ``should_continue() and my_gen == get_lifecycle_generation()``
    to self-identify as stale after a :func:`reset_shutdown_state` call.
    """
    return _lifecycle_generation


def reset_shutdown_state() -> None:
    """Reset for a new in-process server lifecycle (e.g. lifespan startup)."""
    global _should_exit, _lifecycle_generation
    _should_exit = False
    _lifecycle_generation += 1
    _shutdown_listeners.clear()


def sleep_if_should_continue(delay: float) -> None:
    """Sleep up to ``delay`` seconds, waking early if shutdown is requested."""
    if delay <= 1:
        time.sleep(delay)
        return
    start_time = time.time()
    while time.time() - start_time < delay and should_continue():
        time.sleep(1)


async def async_sleep_if_should_continue(delay: float) -> None:
    """Async variant of :func:`sleep_if_should_continue`."""
    if delay <= 1:
        await asyncio.sleep(delay)
        return
    start_time = time.time()
    while time.time() - start_time < delay and should_continue():
        await asyncio.sleep(1)


def add_shutdown_listener(callable: Callable[[], None]) -> UUID:
    """Register a callback; it runs once when :func:`request_process_shutdown` is called."""
    id_ = uuid4()
    _shutdown_listeners[id_] = callable
    return id_


def remove_shutdown_listener(id_: UUID) -> bool:
    """Remove a listener by id. Returns True if it existed."""
    return _shutdown_listeners.pop(id_, None) is not None
