"""Tests for the out-of-loop stall/suspend watchdog and the freeze-aware
run deadline.

These guard the reliability invariant that a frozen event loop (a blocking
call on the loop thread, or an OS suspend) is made *visible* and is *not*
mistaken for an agent hang.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time

import pytest

from backend.app.agent_control_loop import _apply_freeze_credit
from backend.core import loop_watchdog as lw
from backend.core.logging.logger import app_logger


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def msg_types(self) -> set[str]:
        return {getattr(r, 'msg_type', '') for r in self.records}


@pytest.fixture
def capture_app_log():
    handler = _Capture()
    prev_level = app_logger.level
    app_logger.addHandler(handler)
    app_logger.setLevel(logging.DEBUG)
    try:
        yield handler
    finally:
        app_logger.removeHandler(handler)
        app_logger.setLevel(prev_level)


# ── _apply_freeze_credit (pure) ──────────────────────────────────────────


def test_freeze_credit_no_freeze_returns_unchanged():
    started = 1000.0
    new_started, credited = _apply_freeze_credit(
        started, slept=0.5, poll_interval=0.5, grace=30.0
    )
    assert new_started == started
    assert credited == 0.0


def test_freeze_credit_small_overrun_below_grace_is_ignored():
    started = 1000.0
    new_started, credited = _apply_freeze_credit(
        started, slept=10.0, poll_interval=0.5, grace=30.0
    )
    # 9.5s overrun < 30s grace → not a freeze.
    assert new_started == started
    assert credited == 0.0


def test_freeze_credit_large_overrun_is_credited_back():
    started = 1000.0
    # Simulate a 1000s freeze on a 0.5s poll.
    new_started, credited = _apply_freeze_credit(
        started, slept=1000.5, poll_interval=0.5, grace=30.0
    )
    assert credited == pytest.approx(1000.0)
    assert new_started == pytest.approx(started + 1000.0)


def test_freeze_credit_prevents_spurious_hard_timeout():
    # A run that started 1700s ago, then the laptop sleeps 600s. Wall clock
    # since start is 2300s > 1800s cap — but 600s of that was frozen.
    started = 0.0
    max_seconds = 1800.0
    # one freeze poll credited back
    started, credited = _apply_freeze_credit(
        started, slept=600.5, poll_interval=0.5, grace=30.0
    )
    now = 1700.0 + 600.0  # 1700s of real runtime + 600s asleep
    assert credited == pytest.approx(600.0)
    # Deadline check uses (now - started); frozen time is discounted.
    assert (now - started) <= max_seconds  # would have been 2300 without credit


# ── _LoopWatchdog._evaluate (suspend vs loop-stall discrimination) ────────


def _make_watchdog() -> lw._LoopWatchdog:
    return lw._LoopWatchdog(interval=0.05, stall_seconds=0.2, suspend_seconds=5.0)


def test_evaluate_reports_process_suspend_on_large_overshoot(capture_app_log):
    wd = _make_watchdog()
    wd._loop = None  # no real loop needed for this path
    now = time.monotonic()
    # delta hugely exceeds the 0.05s interval → the watchdog thread itself was
    # frozen → whole-process suspend.
    wd._evaluate(now, delta=600.0)
    assert 'PROCESS_SUSPEND' in capture_app_log.msg_types()
    # A suspend must not also be reported as a loop-only stall.
    assert 'EVENT_LOOP_STALL' not in capture_app_log.msg_types()


def test_evaluate_loop_stall_then_recovery(capture_app_log):
    from backend.core.step_phase import set_step_phase

    wd = _make_watchdog()
    wd._loop = None
    wd._seen_tick = True
    set_step_phase('step_inner:get_next_action')
    now = time.monotonic()
    wd._loop_tick = now - 5.0
    wd._evaluate(now, delta=0.05)
    assert 'EVENT_LOOP_STALL' in capture_app_log.msg_types()
    stall = next(
        r
        for r in capture_app_log.records
        if getattr(r, 'msg_type', '') == 'EVENT_LOOP_STALL'
    )
    assert 'step_inner:get_next_action' in stall.getMessage()
    assert getattr(stall, 'step_phase', '') == 'step_inner:get_next_action'
    assert 'Thread' in stall.getMessage()

    wd._loop_tick = time.monotonic()
    wd._evaluate(time.monotonic(), delta=0.05)
    assert 'EVENT_LOOP_RECOVERED' in capture_app_log.msg_types()


def test_evaluate_no_false_stall_before_first_tick(capture_app_log):
    wd = _make_watchdog()
    wd._loop = None
    wd._seen_tick = False  # loop never confirmed running yet
    now = time.monotonic()
    wd._loop_tick = now - 100.0
    wd._evaluate(now, delta=0.05)
    assert 'EVENT_LOOP_STALL' not in capture_app_log.msg_types()


# ── integration: a really-blocked loop is detected with a stack dump ──────


def test_watchdog_detects_blocked_loop(capture_app_log):
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=loop.run_forever, name='wd-test-loop', daemon=True)
    t.start()
    wd = lw._LoopWatchdog(interval=0.05, stall_seconds=0.2, suspend_seconds=1000.0)
    try:
        wd.start(loop)
        # Wait for the first heartbeat to confirm the loop is live
        deadline_seen = time.monotonic() + 3.0
        while not wd._seen_tick and time.monotonic() < deadline_seen:
            time.sleep(0.01)
        assert wd._seen_tick, 'heartbeat was never recorded by the loop'
        # Block the loop thread for ~2.0s with a synchronous sleep.
        loop.call_soon_threadsafe(lambda: time.sleep(2.0))
        # Within the block window, a stall must be reported.
        deadline = time.monotonic() + 3.5
        while time.monotonic() < deadline:
            if 'EVENT_LOOP_STALL' in capture_app_log.msg_types():
                break
            time.sleep(0.05)
        assert 'EVENT_LOOP_STALL' in capture_app_log.msg_types()
    finally:
        wd.stop()
        loop.call_soon_threadsafe(loop.stop)
        t.join(timeout=2.0)
        loop.close()


def test_start_loop_watchdog_disabled(monkeypatch):
    monkeypatch.setattr(lw, 'LOOP_WATCHDOG_ENABLED', False)
    # Use a fresh singleton-like instance via the module function path.
    lw.stop_loop_watchdog()
    loop = asyncio.new_event_loop()
    try:
        lw.start_loop_watchdog(loop)
        assert lw.loop_watchdog_running() is False
    finally:
        loop.close()
