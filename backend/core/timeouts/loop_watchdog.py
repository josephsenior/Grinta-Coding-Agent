"""Out-of-loop watchdog for the main asyncio event loop.

The agent's in-loop safety nets — the per-chunk LLM timeout
(``APP_LLM_STREAM_CHUNK_TIMEOUT_SECONDS``) and the observation-handler
timeout — are all implemented with ``asyncio`` timers.
That means they share the very loop they are meant to protect: if a
**synchronous / blocking call runs on the loop thread** (a sync bridge such as
``call_async_from_sync`` reached from an ``async`` path, a native C call that
holds the GIL, a frozen socket, …) the loop stops turning, *no* timer can
fire, and the freeze leaves **no log line at all** until it ends.  On resume
every overdue timer fires at once — which is exactly the "agent stopped for no
reason, then stalled chunk/observation timers tripped together" signature.

This module closes that blind spot with a **dedicated OS thread** that does not
depend on the loop:

* **Event-loop stall** — the loop is asked to refresh a heartbeat every poll.
  If the heartbeat goes stale for ``stall_seconds`` while this thread is still
  ticking normally, the loop thread is blocked; we dump *every* thread's stack
  to the log so the offending frame names itself.
* **Process suspend / freeze** — if this watchdog thread *itself* did not get
  to run for far longer than its poll interval, the whole process was frozen
  (OS sleep/hibernate, or a long GIL-holding native call).  That is reported
  distinctly so it is never mistaken for an agent hang.

The watchdog only ever *observes and logs*; it never cancels work or mutates
agent state.  Recovery is left to the existing in-loop timers (which fire as
soon as the loop turns again) and to the suspend-aware run deadline.
"""

from __future__ import annotations

import asyncio
import sys
import threading
import time
import traceback

from backend.core.constants import (
    LOOP_WATCHDOG_ENABLED,
    LOOP_WATCHDOG_INTERVAL_SECONDS,
    LOOP_WATCHDOG_STALL_SECONDS,
    LOOP_WATCHDOG_SUSPEND_SECONDS,
)
from backend.core.logging.logger import app_logger as logger

__all__ = [
    'start_loop_watchdog',
    'stop_loop_watchdog',
    'loop_watchdog_running',
]


class _LoopWatchdog:
    """Monitors a single asyncio loop from an independent daemon thread."""

    def __init__(
        self,
        *,
        interval: float,
        stall_seconds: float,
        suspend_seconds: float,
    ) -> None:
        self._interval = max(0.5, float(interval))
        self._stall_seconds = max(self._interval * 2, float(stall_seconds))
        self._suspend_seconds = max(self._interval * 2, float(suspend_seconds))
        # Re-dump the stacks at most this often while a single stall persists,
        # so a multi-minute freeze does not flood the log.
        self._redump_seconds = max(self._stall_seconds, 120.0)

        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_tick = time.monotonic()
        self._seen_tick = False
        self._stalled_since: float | None = None
        self._last_dump = 0.0

        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()

    # ── lifecycle ───────────────────────────────────────────────────────
    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        with self._lock:
            self._loop = loop
            self._loop_tick = time.monotonic()
            self._seen_tick = False
            self._stalled_since = None
            self._last_dump = 0.0
            if self._thread is not None and self._thread.is_alive():
                # Already running — just re-point at the (possibly new) loop.
                self._post_heartbeat()
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run,
                name='grinta-loop-watchdog',
                daemon=True,
            )
            self._thread.start()
            logger.debug(
                'loop watchdog started (interval=%.1fs stall=%.1fs suspend=%.1fs)',
                self._interval,
                self._stall_seconds,
                self._suspend_seconds,
            )

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout)
        self._thread = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ── heartbeat plumbing ──────────────────────────────────────────────
    def _mark_tick(self) -> None:
        # Runs *on the loop thread*; proves the loop is turning.
        self._loop_tick = time.monotonic()
        self._seen_tick = True

    def _post_heartbeat(self) -> None:
        loop = self._loop
        if loop is None:
            return
        try:
            if loop.is_closed():
                return
            loop.call_soon_threadsafe(self._mark_tick)
        except RuntimeError:
            # Loop not running / shutting down — not a stall, just no target.
            pass
        except Exception:
            logger.debug('loop watchdog heartbeat post failed', exc_info=True)

    # ── monitor loop ────────────────────────────────────────────────────
    def _run(self) -> None:
        prev = time.monotonic()
        self._post_heartbeat()
        while not self._stop.wait(self._interval):
            now = time.monotonic()
            delta = now - prev
            prev = now
            try:
                self._evaluate(now, delta)
            except Exception:
                logger.debug('loop watchdog evaluate failed', exc_info=True)

    def _evaluate(self, now: float, delta: float) -> None:
        # (A) Whole-process freeze: this thread itself did not run on schedule.
        # A loop-only block does *not* delay this thread, so a large overshoot
        # means the entire process was suspended (OS sleep/hibernate or a long
        # GIL-holding native call).
        overshoot = delta - self._interval
        if overshoot >= self._suspend_seconds:
            logger.warning(
                'PROCESS_SUSPEND: watchdog thread was frozen ~%.0fs (poll '
                'interval is %.0fs). The whole process stalled — OS '
                'sleep/hibernate or a long GIL-holding native call. Every '
                'asyncio timer was overdue and fires together on resume; this '
                'frozen time is NOT an agent hang and is not charged against '
                'the run budget.',
                delta,
                self._interval,
                extra={
                    'msg_type': 'PROCESS_SUSPEND',
                    'frozen_seconds': round(delta, 1),
                },
            )
            try:
                from backend.core.timeouts.suspend_aware_deadline import (
                    credit_active_deadlines_process_suspend,
                )

                credit_active_deadlines_process_suspend(delta)
            except Exception:
                logger.debug(
                    'failed to credit suspend-aware deadlines after PROCESS_SUSPEND',
                    exc_info=True,
                )
            # The loop was frozen alongside us; treat its heartbeat as fresh.
            self._loop_tick = now
            self._seen_tick = True
            self._stalled_since = None
            self._last_dump = 0.0
            self._post_heartbeat()
            return

        # (B) Event-loop-only stall: we ran on time but the loop is not ticking.
        if self._seen_tick:
            loop_age = now - self._loop_tick
            if loop_age >= self._stall_seconds:
                if self._stalled_since is None:
                    self._stalled_since = self._loop_tick
                if (
                    self._last_dump <= 0.0
                    or now - self._last_dump >= self._redump_seconds
                ):
                    self._last_dump = now
                    self._log_stall(loop_age)
            elif self._stalled_since is not None:
                logger.warning(
                    'EVENT_LOOP_RECOVERED: main loop resumed after ~%.0fs blocked.',
                    now - self._stalled_since,
                    extra={
                        'msg_type': 'EVENT_LOOP_RECOVERED',
                        'blocked_seconds': round(now - self._stalled_since, 1),
                    },
                )
                self._stalled_since = None
                self._last_dump = 0.0

        self._post_heartbeat()

    def _log_stall(self, loop_age: float) -> None:
        from backend.core.step_phase import get_step_phase

        phase = get_step_phase()
        try:
            stacks = _format_thread_stacks()
        except Exception:
            stacks = '(failed to capture thread stacks)'
        logger.error(
            'EVENT_LOOP_STALL: the main asyncio loop has made no progress for '
            '~%.0fs (step phase=%r). In-loop timers (liveness ceiling, chunk '
            'timeout, observation-handler timeout) cannot fire while the loop '
            'thread is blocked, so this is almost certainly a synchronous/'
            'blocking call running on the loop thread. Thread stacks below '
            'pinpoint it:\n%s',
            loop_age,
            phase,
            stacks,
            extra={
                'msg_type': 'EVENT_LOOP_STALL',
                'stalled_seconds': round(loop_age, 1),
                'step_phase': phase,
            },
        )


def _format_thread_stacks() -> str:
    """Render a stack trace for every live thread (loop thread included)."""
    frames = sys._current_frames()  # noqa: SLF001 — intentional diagnostic use
    by_ident = {t.ident: t for t in threading.enumerate()}
    blocks: list[str] = []
    for ident, frame in frames.items():
        thread = by_ident.get(ident)
        name = thread.name if thread is not None else '?'
        daemon = thread.daemon if thread is not None else '?'
        header = f'--- Thread {name!r} (id={ident}, daemon={daemon}) ---'
        try:
            body = ''.join(traceback.format_stack(frame))
        except Exception:
            body = '(stack unavailable)\n'
        blocks.append(f'{header}\n{body}')
    return '\n'.join(blocks)


_WATCHDOG = _LoopWatchdog(
    interval=LOOP_WATCHDOG_INTERVAL_SECONDS,
    stall_seconds=LOOP_WATCHDOG_STALL_SECONDS,
    suspend_seconds=LOOP_WATCHDOG_SUSPEND_SECONDS,
)


def start_loop_watchdog(loop: asyncio.AbstractEventLoop | None = None) -> None:
    """Start (or re-point) the loop watchdog at *loop*.

    Idempotent and safe to call from any thread.  When *loop* is ``None`` the
    currently running loop is used; if there is none the call is a no-op.
    Disabled entirely when ``GRINTA_LOOP_WATCHDOG=0``.
    """
    if not LOOP_WATCHDOG_ENABLED:
        return
    if loop is None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
    try:
        _WATCHDOG.start(loop)
    except Exception:
        # The watchdog must never break the app it is protecting.
        logger.debug('failed to start loop watchdog', exc_info=True)


def stop_loop_watchdog() -> None:
    """Stop the watchdog thread (used on shutdown and in tests)."""
    try:
        _WATCHDOG.stop()
    except Exception:
        logger.debug('failed to stop loop watchdog', exc_info=True)


def loop_watchdog_running() -> bool:
    """Return ``True`` while the watchdog daemon thread is alive."""
    return _WATCHDOG.is_running()
