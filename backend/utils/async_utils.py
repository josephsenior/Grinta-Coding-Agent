"""Async helper utilities for bridging sync/async execution and task coordination."""

from __future__ import annotations

import asyncio
import atexit
import logging
import os
import sys
import threading
import traceback
from collections.abc import Awaitable, Callable, Coroutine, Iterable
from concurrent import futures
from concurrent.futures import ThreadPoolExecutor
from typing import Any, ParamSpec, TypeVar

from backend.core.constants import GENERAL_TIMEOUT

_logger = logging.getLogger(__name__)

# ── On-loop bridge tripwire ─────────────────────────────────────────────
# ``call_async_from_sync`` blocks its calling thread (``futures.wait``).  When
# that thread is an event-loop thread, the loop freezes and *no* in-loop timer
# can fire — the silent multi-minute-hang failure mode.  The proper offload
# pattern (``call_sync_from_async`` / ``call_coro_in_bg_thread``) runs the
# bridge on a worker thread where there is no running loop, so it never trips
# this wire.  Direct on-loop calls are surfaced loudly (once per call site),
# and fatally when ``GRINTA_STRICT_LOOP_BRIDGE`` is set.
_STRICT_LOOP_BRIDGE = os.getenv('GRINTA_STRICT_LOOP_BRIDGE', '0').strip().lower() in {
    '1',
    'true',
    'yes',
    'on',
}
_seen_on_loop_bridges: set[str] = set()
_on_loop_bridge_lock = threading.Lock()


def _warn_if_on_loop_thread(corofn: Any) -> None:
    """Flag ``call_async_from_sync`` calls made on an event-loop thread.

    A no-op (one cheap ``get_running_loop``) on the safe, intended off-loop
    path.  On a loop thread it emits a de-duplicated ``BRIDGE_ON_LOOP`` warning
    naming the call site (so the path can be made async or offloaded), or
    raises in strict mode so tests catch the regression.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return  # Off-loop (worker thread / plain sync): this is correct usage.

    name = getattr(corofn, '__name__', repr(corofn))
    try:
        caller = sys._getframe(2)  # 0=here, 1=call_async_from_sync, 2=caller
        site = f'{caller.f_code.co_filename}:{caller.f_lineno}'
    except Exception:
        site = '<unknown>'

    if _STRICT_LOOP_BRIDGE:
        raise RuntimeError(
            f'call_async_from_sync({name}) was invoked on a running event loop '
            f'(thread={threading.current_thread().name!r}) at {site}: this '
            f'blocks the loop thread. Await the coroutine directly, or offload '
            f'via call_sync_from_async()/call_coro_in_bg_thread().'
        )

    key = f'{name}@{site}'
    with _on_loop_bridge_lock:
        first_seen = key not in _seen_on_loop_bridges
        if first_seen:
            _seen_on_loop_bridges.add(key)
    if first_seen:
        stack = ''.join(traceback.format_stack(limit=12))
        _logger.warning(
            'BRIDGE_ON_LOOP: call_async_from_sync(%s) called on event-loop '
            'thread %r at %s — this blocks the loop (no in-loop timer can fire '
            'until it returns). Await the coroutine directly, or offload via '
            'call_sync_from_async()/call_coro_in_bg_thread(). Stack:\n%s',
            name,
            threading.current_thread().name,
            site,
            stack,
            extra={'msg_type': 'BRIDGE_ON_LOOP', 'bridge': name, 'site': site},
        )
    else:
        _logger.debug(
            'BRIDGE_ON_LOOP (repeat): call_async_from_sync(%s) on loop at %s',
            name,
            site,
        )

# Module-level set to hold strong references to background tasks.
# Without this, tasks created via ``asyncio.create_task()`` may be
# garbage-collected before completion (CPython GC behaviour).
_background_tasks: set[asyncio.Task[Any]] = set()

_P = ParamSpec('_P')
_R = TypeVar('_R')


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
def _get_max_workers() -> int:
    raw = os.getenv('APP_THREAD_POOL_MAX_WORKERS', '32')
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        _logger.warning(
            'Invalid APP_THREAD_POOL_MAX_WORKERS=%r; using default 32',
            raw,
        )
        return 32
    if parsed <= 0:
        _logger.warning(
            'Non-positive APP_THREAD_POOL_MAX_WORKERS=%r; using default 32',
            raw,
        )
        return 32
    return parsed


_MAX_WORKERS = _get_max_workers()
EXECUTOR: ThreadPoolExecutor = ThreadPoolExecutor(max_workers=_MAX_WORKERS)


def _get_sync_from_async_workers() -> int:
    """Dedicated capacity for sync functions awaited from the main event loop."""
    raw = os.getenv('GRINTA_SYNC_FROM_ASYNC_POOL_WORKERS')
    default = max(4, min(_MAX_WORKERS, 16))
    if raw is None:
        return default
    try:
        n = int(raw)
    except (TypeError, ValueError):
        _logger.warning(
            'Invalid GRINTA_SYNC_FROM_ASYNC_POOL_WORKERS=%r; using default %d',
            raw,
            default,
        )
        return default
    return max(1, min(n, 64))


# Keep sync work awaited by the event loop off asyncio's implicit default
# executor. This bounds worker growth and keeps nested call_async_from_sync work
# from starving on the shared EXECUTOR.
SYNC_FROM_ASYNC_EXECUTOR: ThreadPoolExecutor = ThreadPoolExecutor(
    max_workers=_get_sync_from_async_workers(),
    thread_name_prefix='grinta-sync-from-async',
)


def _debugger_sync_pool_workers() -> int:
    """Dedicated capacity for :class:`~backend.ledger.action.DebuggerAction` sync bridges."""
    raw = os.getenv('GRINTA_DEBUGGER_SYNC_POOL_WORKERS', '6')
    try:
        n = int(raw)
    except (TypeError, ValueError):
        _logger.warning(
            'Invalid GRINTA_DEBUGGER_SYNC_POOL_WORKERS=%r; using default 6',
            raw,
        )
        return 6
    return max(2, min(n, 32))


# Separate pool so debugger ``run_action`` never queues behind unrelated
# ``call_async_from_sync`` / bridge work on ``EXECUTOR`` (seen in app.log as
# ``_handle_action START DebuggerAction`` with no ``DEBUGGER_DISPATCH`` for minutes).
DEBUGGER_SYNC_EXECUTOR: ThreadPoolExecutor = ThreadPoolExecutor(
    max_workers=_debugger_sync_pool_workers(),
    thread_name_prefix='grinta-dbg-sync',
)


def _shutdown_executor_atexit() -> None:
    """Cancel queued work and request worker termination at interpreter exit.

    ``ThreadPoolExecutor`` worker threads are non-daemon, so without an
    explicit shutdown they can keep the process alive after the CLI's main
    coroutine returns — most visibly on Windows, where leftover workers
    holding subprocess/SQLite handles delay process exit.

    ``cancel_futures=True`` drops queued tasks; running tasks are not
    interrupted but are bounded by their own timeouts.
    """
    for ex in (EXECUTOR, SYNC_FROM_ASYNC_EXECUTOR, DEBUGGER_SYNC_EXECUTOR):
        try:
            ex.shutdown(wait=True, cancel_futures=True)
        except Exception:
            # atexit handlers must never raise.
            pass


atexit.register(_shutdown_executor_atexit)

# Hard cap for cancelling stray tasks after the main coroutine completes (e.g. browser-use CDP tasks).
_LOOP_SHUTDOWN_WAIT_SEC = float(os.getenv('CALL_ASYNC_LOOP_SHUTDOWN_WAIT_SEC', '2.0'))
# Cap for shutdown_asyncgens / shutdown_default_executor — the latter can otherwise block for minutes
# on Windows when browser-use leaves work on the loop's default executor threads.
_LOOP_FINALIZE_WAIT_SEC = float(os.getenv('CALL_ASYNC_LOOP_FINALIZE_WAIT_SEC', '3.0'))


def _cancel_pending_tasks_bounded(
    loop: asyncio.AbstractEventLoop, *, timeout_sec: float
) -> None:
    """Cancel tasks still scheduled on *loop*; wait at most *timeout_sec* for cancellation.

    ``asyncio.run`` can block in loop teardown if third-party code leaves tasks that do not
    finish promptly when cancelled. This keeps ``call_async_from_sync`` worker threads bounded.
    """
    pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
    if not pending:
        return
    for t in pending:
        t.cancel()
    gather_coro = asyncio.gather(*pending, return_exceptions=True)
    try:
        loop.run_until_complete(asyncio.wait_for(gather_coro, timeout=timeout_sec))
    except TimeoutError:
        undone = sum(1 for t in pending if not t.done())
        _logger.warning(
            'call_async_from_sync: %d task(s) still pending after %.1fs shutdown wait',
            undone,
            timeout_sec,
        )


async def call_sync_from_async(
    fn: Callable[..., Any], *args: Any, **kwargs: Any
) -> Any:
    """Run a synchronous function in the background thread-pool and await the result.

    The returned future is **not** cancellable because synchronous code cannot
    be interrupted once scheduled.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        SYNC_FROM_ASYNC_EXECUTOR,
        lambda: fn(*args, **kwargs),
    )


def call_async_from_sync(
    corofn: Callable[_P, Awaitable[_R]] | None,
    timeout: float = GENERAL_TIMEOUT,
    *args: _P.args,
    **kwargs: _P.kwargs,
) -> _R:
    """Shorthand for running a coroutine in the default background thread pool executor.

    and awaiting the result.
    """
    if corofn is None:
        msg = 'corofn is None'
        raise ValueError(msg)
    if not asyncio.iscoroutinefunction(corofn):
        msg = 'corofn is not a coroutine function'
        raise ValueError(msg)

    # Tripwire: blocking the loop thread here is the silent-hang failure mode.
    _warn_if_on_loop_thread(corofn)

    async def arun() -> _R:
        """Execute target coroutine function with provided args/kwargs."""
        coro = corofn(*args, **kwargs)
        return await coro

    def run() -> _R:
        """Run coroutine in a fresh event loop within the worker thread.

        After the main coroutine returns, cancel any remaining tasks with a bounded wait so
        libraries that spawn background asyncio work (e.g. browser CDP handlers) cannot keep
        the thread parked indefinitely during ``asyncio.run`` teardown.
        """
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(arun())
            _cancel_pending_tasks_bounded(loop, timeout_sec=_LOOP_SHUTDOWN_WAIT_SEC)
            return result
        finally:
            # Unbounded shutdown_asyncgens / shutdown_default_executor can hang (esp. default
            # executor joining browser/CDP threadpool work). Always bound wall time.
            #
            # Optimisation: when the loop never actually scheduled a default executor
            # (the common case for the synchronous tools — file IO, debugger, lsp_query)
            # ``shutdown_default_executor`` is still serialised through a 3 s wait per
            # call. Skip both finalise steps when the loop is empty to remove ~5 s of
            # invisible tail latency from every sync tool invocation.
            fin = _LOOP_FINALIZE_WAIT_SEC
            has_residual_tasks = any(not t.done() for t in asyncio.all_tasks(loop))
            has_default_executor = getattr(loop, '_default_executor', None) is not None
            if has_residual_tasks:
                try:
                    loop.run_until_complete(
                        asyncio.wait_for(loop.shutdown_asyncgens(), timeout=fin)
                    )
                except (TimeoutError, Exception):
                    pass
            if has_default_executor:
                try:
                    loop.run_until_complete(
                        asyncio.wait_for(loop.shutdown_default_executor(), timeout=fin)
                    )
                except (TimeoutError, Exception):
                    pass
            asyncio.set_event_loop(None)
            try:
                loop.close()
            except Exception:
                pass

    if getattr(EXECUTOR, '_shutdown', False):
        return run()
    future = EXECUTOR.submit(run)
    futures.wait([future], timeout=timeout or None)
    if not future.done():
        _logger.warning(
            'call_async_from_sync: future not done after %.1fs timeout for %s',
            timeout,
            getattr(corofn, '__name__', corofn),
        )
        # Cancel to avoid indefinite blocking.  result() with a timeout
        # ensures we don't park the calling thread forever.
        future.cancel()
        raise TimeoutError(
            f'call_async_from_sync timed out after {timeout}s for '
            f'{getattr(corofn, "__name__", corofn)}'
        )
    return future.result()


async def call_coro_in_bg_thread(
    corofn: Callable[..., Awaitable[Any]] | None,
    timeout_sec: float = GENERAL_TIMEOUT,
    *args: object,
    **kwargs: object,
) -> Any:
    """Run an async coroutine from async code without blocking the event loop.

    Preferred replacement for ``call_async_from_sync`` when the caller is
    already on the event loop (middleware, services, orchestration).
    """
    import importlib

    mod = importlib.import_module('backend.utils.async_utils')
    delegate = mod.call_sync_from_async
    return await delegate(call_async_from_sync, corofn, timeout_sec, *args, **kwargs)


run_async_bridge = call_coro_in_bg_thread


async def wait_all(
    iterable: Iterable[Coroutine], wait_timeout_sec: int = GENERAL_TIMEOUT
) -> list:
    """Shorthand for waiting for all the coroutines in the iterable given in parallel.

    Creates a task for each coroutine. Returns a list of results in the original order. If any single task
    raised an exception, this is raised. If multiple tasks raised exceptions, an AsyncException is raised
    containing all exceptions.
    """
    tasks = [asyncio.create_task(c) for c in iterable]
    if not tasks:
        return []

    done, pending = await asyncio.wait(tasks, timeout=wait_timeout_sec)
    if pending:
        _handle_pending_tasks(done, pending)
        raise TimeoutError

    return _collect_results(tasks)


def _handle_pending_tasks(done: set[asyncio.Task], pending: set[asyncio.Task]) -> None:
    """Log and cancel pending tasks."""
    logger = logging.getLogger(__name__)
    pending_info = []
    for task in pending:
        coro_name = getattr(task.get_coro(), '__name__', 'unknown')
        pending_info.append(f'  - {coro_name}')

    logger.error(
        'Timeout waiting for %s task(s) to complete. Completed: %s, Pending: %s\n'
        'Pending tasks: %s',
        len(pending),
        len(done),
        len(pending),
        '\n'.join(pending_info) if pending_info else 'Unable to get task names',
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
        return '\n'.join(str(e) for e in self.exceptions)


async def run_in_loop(
    coro: Coroutine,
    loop: asyncio.AbstractEventLoop,
    timeout_sec: float = GENERAL_TIMEOUT,
) -> Any:
    """Run `coro` on `loop`, using thread handoff when switching event loops."""
    running_loop = asyncio.get_running_loop()
    if running_loop == loop:
        return await coro
    return await call_sync_from_async(_run_in_loop, coro, loop, timeout_sec)


def _run_in_loop(
    coro: Coroutine, loop: asyncio.AbstractEventLoop, timeout_sec: float
) -> Any:
    """Run a coroutine in a specific event loop with timeout.

    Args:
        coro: The coroutine to run.
        loop: The event loop to run the coroutine in.
        timeout_sec: Timeout in seconds for the coroutine execution.

    Returns:
        The result of the coroutine execution.

    """
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=timeout_sec)


# ---------------------------------------------------------------------------
# Main event loop registry
# ---------------------------------------------------------------------------
# The application's main event loop (typically uvicorn's) is registered here
# so that ``run_or_schedule`` can dispatch coroutines to it even when called
# from background threads (e.g. EventStream's ThreadPoolExecutor dispatch).
# Without this, ``run_or_schedule`` would create throw-away event loops whose
# tasks are orphaned as soon as ``run_until_complete`` finishes.
_main_event_loop: asyncio.AbstractEventLoop | None = None
_main_loop_lock = threading.Lock()

# A cached fallback loop reused across run_or_schedule() path-3 calls.
# Created lazily on first use, reused for subsequent calls, closed only
# on process exit or explicit cleanup.
_fallback_loop: asyncio.AbstractEventLoop | None = None
_fallback_loop_lock = threading.Lock()


def set_main_event_loop(loop: asyncio.AbstractEventLoop | None = None) -> None:
    """Register the application's main event loop.

    Call this once from the application startup (e.g. FastAPI lifespan).
    If *loop* is ``None``, the currently running loop is used.
    """
    global _main_event_loop  # noqa: PLW0603
    with _main_loop_lock:
        if loop is None:
            loop = asyncio.get_running_loop()
        _main_event_loop = loop

    # Point the out-of-loop stall/suspend watchdog at the (possibly new) main
    # loop.  Deferred import keeps this low-level module free of heavier deps
    # and avoids import cycles.  Idempotent and never raises into callers.
    try:
        from backend.core.loop_watchdog import start_loop_watchdog

        start_loop_watchdog(loop)
    except Exception:
        _logger.debug('failed to start loop watchdog', exc_info=True)


def get_main_event_loop() -> asyncio.AbstractEventLoop | None:
    """Return the registered main event loop, or ``None``."""
    with _main_loop_lock:
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
        create_tracked_task(coro, name='run_or_schedule')
    except RuntimeError:
        # Loop was closed between the threadsafe call and execution.
        _logger.debug('Main loop closed before run_or_schedule task could be created')


def run_or_schedule(coro: Coroutine[Any, Any, Any]) -> None:
    """Execute *coro* on an event loop, creating one if necessary.

    This centralises a pattern that was previously duplicated across
    ``SessionOrchestrator``, ``Runtime``, ``Session``, and ``Memory``:

    1. If a loop is already running in the current thread → schedule
       *coro* as a background task on that loop.
    2. If a main loop has been registered (via :func:`set_main_event_loop`)
       and it is still running → schedule *coro* on it via
       ``call_soon_threadsafe``.
    3. Otherwise fall back to a synchronous ``run_until_complete`` on a
       fresh disposable loop.

    The function is intentionally background-only; callers that need the
    result should ``await`` the coroutine directly instead.
    """
    # 1. Currently inside a running loop → create a task directly.
    loop = get_active_loop()
    if loop is not None:
        create_tracked_task(coro, name='run_or_schedule')
        return

    # 2. Dispatch to the registered main loop (from a background thread).
    main = _main_event_loop
    if main is not None and main.is_running():
        main.call_soon_threadsafe(_schedule_on_main_loop, coro)
        return

    # 3. No running loop — fall back to a reusable cached loop.  Creating
    # a fresh loop per call is expensive and orphans tasks.  We keep one
    # cached loop for path-3 calls and reuse it across all such calls
    # within the process lifetime.  Threads sharing this loop is safe since
    # each call's run_until_complete is a discrete, self-contained unit.
    with _fallback_loop_lock:
        global _fallback_loop  # noqa: PLW0603
        if _fallback_loop is None or _fallback_loop.is_closed():
            _fallback_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(_fallback_loop)

            def _close_fallback_loop() -> None:
                global _fallback_loop  # noqa: PLW0603
                if _fallback_loop is not None and not _fallback_loop.is_closed():
                    _fallback_loop.run_until_complete(
                        _fallback_loop.shutdown_asyncgens()
                    )
                    _fallback_loop.close()
                    _fallback_loop = None

            atexit.register(_close_fallback_loop)
        _fallback_loop.run_until_complete(coro)


async def drain_step_barrier(
    *,
    has_outstanding: Callable[[], bool] | None = None,
    max_rounds: int = 20,
    timeout: float = 2.0,
    poll_interval: float = 0.05,
) -> bool:
    """Drain background tasks and wait for outstanding pending actions to clear.

    Returns True when both the background task set and optional pending predicate
    report idle; False when *timeout* expires with pending work still outstanding.
    """
    from backend.core.logger import app_logger as logger
    from backend.core.suspend_aware_deadline import SuspendAwareDeadline

    deadline = SuspendAwareDeadline(timeout, poll_interval=poll_interval)
    try:
        while not deadline.expired():
            await drain_background_tasks(
                max_rounds=max_rounds,
                timeout=poll_interval,
            )
            if has_outstanding is None or not has_outstanding():
                return True
            await asyncio.sleep(poll_interval)
            deadline.credit_poll_sleep(poll_interval)
        logger.warning(
            'drain_step_barrier timed out after %.1fs with outstanding pending work',
            timeout,
            extra={'msg_type': 'DRAIN_STEP_BARRIER_TIMEOUT'},
        )
        return False
    finally:
        deadline.close()


async def drain_background_tasks(
    *,
    max_rounds: int = 20,
    task_set: set[asyncio.Task[Any]] | None = None,
    timeout: float | None = None,  # noqa: ASYNC109
) -> None:
    """Await all in-flight background tasks spawned via ``run_or_schedule``.

    Repeatedly snapshots the task set and gathers pending tasks until no new
    tasks appear (each task may itself schedule further tasks).  This is a
    proper barrier replacement for ``await asyncio.sleep(0)`` which only
    yields once and does not guarantee that background callbacks have
    completed.

    Args:
        max_rounds: Safety cap to prevent infinite loops if tasks keep
            spawning new tasks indefinitely.
        task_set: The task set to drain. Defaults to the module-level
            ``_background_tasks``.
        timeout: Optional per-round timeout in seconds. Prevents hanging
            indefinitely when a background task never completes.
    """
    target = task_set if task_set is not None else _background_tasks
    for _ in range(max_rounds):
        pending = {t for t in target if not t.done()}
        if not pending:
            break
        if timeout is not None:
            await asyncio.wait(pending, timeout=timeout)
        else:
            await asyncio.gather(*pending, return_exceptions=True)
