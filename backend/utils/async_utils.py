"""Async helper utilities for bridging sync/async execution and task coordination."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable, Coroutine, Iterable
from concurrent import futures
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from backend.core.constants import GENERAL_TIMEOUT

_logger = logging.getLogger(__name__)

# Module-level set to hold strong references to fire-and-forget tasks.
# Without this, tasks created via ``asyncio.create_task()`` may be
# garbage-collected before completion (CPython GC behaviour).
_background_tasks: set[asyncio.Task[Any]] = set()


def create_tracked_task(
    coro: Coroutine[Any, Any, Any],
    *,
    name: str | None = None,
    task_set: set[asyncio.Task[Any]] | None = None,
) -> asyncio.Task[Any]:
    """Create an asyncio task with a strong reference to prevent GC.

    This is the canonical replacement for bare ``asyncio.create_task()``
    where the returned ``Task`` would otherwise be discarded. The task is
    held in *task_set* (defaults to the module-level ``_background_tasks``)
    and automatically removed when it completes.

    Args:
        coro: The coroutine to schedule.
        name: Optional name for the task (useful for debugging).
        task_set: The ``set`` to store the task in.  Defaults to the
                  module-level ``_background_tasks``.

    Returns:
        The created ``asyncio.Task``.
    """
    target = task_set if task_set is not None else _background_tasks
    task = asyncio.create_task(coro, name=name)
    target.add(task)
    task.add_done_callback(target.discard)
    return task


# Bounded worker pool — defaults to min(32, CPU+4) but can be overridden via env.
_MAX_WORKERS = int(os.getenv("FORGE_THREAD_POOL_MAX_WORKERS", "32"))
EXECUTOR: ThreadPoolExecutor = ThreadPoolExecutor(max_workers=_MAX_WORKERS)


async def call_sync_from_async(
    fn: Callable[..., Any], *args: Any, **kwargs: Any
) -> Any:
    """Run a synchronous function in the background thread-pool and await the result.

    The returned future is **not** cancellable because synchronous code cannot
    be interrupted once scheduled.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: fn(*args, **kwargs))


def call_async_from_sync(
    corofn: Callable[..., Awaitable[Any]] | None,
    timeout: float = GENERAL_TIMEOUT,
    *args,
    **kwargs,
) -> Any:
    """Shorthand for running a coroutine in the default background thread pool executor.

    and awaiting the result.
    """
    if corofn is None:
        msg = "corofn is None"
        raise ValueError(msg)
    if not asyncio.iscoroutinefunction(corofn):
        msg = "corofn is not a coroutine function"
        raise ValueError(msg)

    async def arun():
        """Execute target coroutine function with provided args/kwargs."""
        coro = corofn(*args, **kwargs)
        return await coro

    def run():
        """Run coroutine in fresh event loop within worker thread."""
        loop_for_thread = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop_for_thread)
            return asyncio.run(arun())
        finally:
            loop_for_thread.close()

    if getattr(EXECUTOR, "_shutdown", False):
        return run()
    future = EXECUTOR.submit(run)
    futures.wait([future], timeout=timeout or None)
    if not future.done():
        _logger.warning(
            "call_async_from_sync: future not done after %.1fs timeout for %s",
            timeout,
            getattr(corofn, "__name__", corofn),
        )
        # Cancel to avoid indefinite blocking.  result() with a timeout
        # ensures we don't park the calling thread forever.
        future.cancel()
        raise TimeoutError(
            f"call_async_from_sync timed out after {timeout}s for "
            f"{getattr(corofn, '__name__', corofn)}"
        )
    return future.result()


async def call_coro_in_bg_thread(
    corofn: Callable[..., Awaitable[Any]] | None,
    timeout: float = GENERAL_TIMEOUT,
    *args,
    **kwargs,
) -> None:
    """Function for running a coroutine in a background thread.

    Resolve the delegate at call-time from the canonical module to ensure
    test monkeypatches apply deterministically even under import edge-cases.
    """
    import importlib

    mod = importlib.import_module("backend.utils.async_utils")
    delegate = getattr(mod, "call_sync_from_async")
    await delegate(call_async_from_sync, corofn, timeout, *args, **kwargs)


async def wait_all(
    iterable: Iterable[Coroutine], timeout: int = GENERAL_TIMEOUT
) -> list:
    """Shorthand for waiting for all the coroutines in the iterable given in parallel.

    Creates a task for each coroutine. Returns a list of results in the original order. If any single task
    raised an exception, this is raised. If multiple tasks raised exceptions, an AsyncException is raised
    containing all exceptions.
    """
    tasks = [asyncio.create_task(c) for c in iterable]
    if not tasks:
        return []

    done, pending = await asyncio.wait(tasks, timeout=timeout)
    if pending:
        _handle_pending_tasks(done, pending)
        raise TimeoutError

    return _collect_results(tasks)


def _handle_pending_tasks(done: set[asyncio.Task], pending: set[asyncio.Task]) -> None:
    """Log and cancel pending tasks."""
    logger = logging.getLogger(__name__)
    pending_info = []
    for task in pending:
        coro_name = getattr(task.get_coro(), "__name__", "unknown")
        pending_info.append(f"  - {coro_name}")

    logger.error(
        "Timeout waiting for %s task(s) to complete. Completed: %s, Pending: %s\n"
        "Pending tasks: %s",
        len(pending),
        len(done),
        len(pending),
        "\n".join(pending_info) if pending_info else "Unable to get task names",
    )
    for task in pending:
        task.cancel()


def _collect_results(tasks: list[asyncio.Task]) -> list[Any]:
    """Collect results from tasks and raise aggregated exceptions if needed."""
    results = []
    errors = []
    for task in tasks:
        try:
            results.append(task.result())
        except Exception as e:
            errors.append(e)

    if errors:
        if len(errors) == 1:
            raise errors[0]
        raise AsyncException(errors)

    return results


class AsyncException(Exception):
    """Aggregate exception capturing multiple errors raised by wait_all."""

    def __init__(self, exceptions) -> None:
        """Store the sequence of exceptions aggregated from awaited tasks."""
        self.exceptions = exceptions

    def __str__(self) -> str:
        """Join aggregated exception messages into a newline-delimited string."""
        return "\n".join(str(e) for e in self.exceptions)


async def run_in_loop(
    coro: Coroutine, loop: asyncio.AbstractEventLoop, timeout: float = GENERAL_TIMEOUT
) -> Any:
    """Run `coro` on `loop`, using thread handoff when switching event loops."""
    running_loop = asyncio.get_running_loop()
    if running_loop == loop:
        return await coro
    return await call_sync_from_async(_run_in_loop, coro, loop, timeout)


def _run_in_loop(
    coro: Coroutine, loop: asyncio.AbstractEventLoop, timeout: float
) -> Any:
    """Run a coroutine in a specific event loop with timeout.

    Args:
        coro: The coroutine to run.
        loop: The event loop to run the coroutine in.
        timeout: Timeout in seconds for the coroutine execution.

    Returns:
        The result of the coroutine execution.

    """
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=timeout)


# ---------------------------------------------------------------------------
# Main event loop registry
# ---------------------------------------------------------------------------
# The application's main event loop (typically uvicorn's) is registered here
# so that ``run_or_schedule`` can dispatch coroutines to it even when called
# from background threads (e.g. EventStream's ThreadPoolExecutor dispatch).
# Without this, ``run_or_schedule`` would create throw-away event loops whose
# tasks are orphaned as soon as ``run_until_complete`` finishes.
_main_event_loop: asyncio.AbstractEventLoop | None = None


def set_main_event_loop(loop: asyncio.AbstractEventLoop | None = None) -> None:
    """Register the application's main event loop.

    Call this once from the application startup (e.g. FastAPI lifespan).
    If *loop* is ``None``, the currently running loop is used.
    """
    global _main_event_loop  # noqa: PLW0603
    if loop is None:
        loop = asyncio.get_running_loop()
    _main_event_loop = loop


def get_main_event_loop() -> asyncio.AbstractEventLoop | None:
    """Return the registered main event loop, or ``None``."""
    return _main_event_loop


def get_active_loop() -> asyncio.AbstractEventLoop | None:
    """Get the currently running event loop, if any.

    Returns:
        The running loop if it exists and is active, otherwise None.
    """
    try:
        loop = asyncio.get_running_loop()
        if loop.is_running():
            return loop
    except RuntimeError:
        pass
    return None


def _schedule_on_main_loop(coro: Coroutine[Any, Any, Any]) -> None:
    """Schedule *coro* as a tracked task on the main event loop.

    Called via ``call_soon_threadsafe`` so the actual
    ``create_tracked_task`` happens inside the main loop's thread.
    """
    try:
        create_tracked_task(coro, name="run_or_schedule")
    except RuntimeError:
        # Loop was closed between the threadsafe call and execution.
        _logger.debug("Main loop closed before run_or_schedule task could be created")


def run_or_schedule(coro: Coroutine[Any, Any, Any]) -> None:
    """Execute *coro* on an event loop, creating one if necessary.

    This centralises a pattern that was previously duplicated across
    ``AgentController``, ``Runtime``, ``Session``, and ``Memory``:

    1. If a loop is already running in the current thread → schedule
       *coro* as a background task on that loop.
    2. If a main loop has been registered (via :func:`set_main_event_loop`)
       and it is still running → schedule *coro* on it via
       ``call_soon_threadsafe``.
    3. Otherwise fall back to a synchronous ``run_until_complete`` on a
       fresh disposable loop.

    The function is intentionally fire-and-forget; callers that need the
    result should ``await`` the coroutine directly instead.
    """
    # 1. Currently inside a running loop → create a task directly.
    loop = get_active_loop()
    if loop is not None:
        create_tracked_task(coro, name="run_or_schedule")
        return

    # 2. Dispatch to the registered main loop (from a background thread).
    main = _main_event_loop
    if main is not None and main.is_running():
        main.call_soon_threadsafe(_schedule_on_main_loop, coro)
        return

    # 3. No running loop — fall back to synchronous execution.
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(coro)
    finally:
        loop.close()
