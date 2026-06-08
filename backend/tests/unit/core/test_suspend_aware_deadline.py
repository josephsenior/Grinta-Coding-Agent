"""Tests for suspend-aware deadlines."""

from __future__ import annotations

from backend.core.suspend_aware_deadline import (
    SuspendAwareDeadline,
    credit_active_deadlines_process_suspend,
)


def test_poll_sleep_credit():
    deadline = SuspendAwareDeadline(100.0, poll_interval=0.5, freeze_grace_seconds=30.0)
    started = deadline._started  # noqa: SLF001
    credited = deadline.credit_poll_sleep(600.5)
    assert credited == 600.0
    assert deadline.elapsed() < 1.0
    assert not deadline.expired()
    deadline.close()


def test_process_suspend_credits_active_deadlines():
    deadline = SuspendAwareDeadline(1800.0, freeze_grace_seconds=30.0)
    before = deadline.elapsed()
    credit_active_deadlines_process_suspend(600.0)
    assert deadline.elapsed() < before + 1.0
    deadline.close()


def test_zero_budget_never_expires():
    deadline = SuspendAwareDeadline(0.0)
    deadline.credit_poll_sleep(10_000.0)
    assert not deadline.expired()
    deadline.close()
