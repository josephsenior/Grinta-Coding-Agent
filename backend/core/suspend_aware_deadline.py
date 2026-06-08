"""Wall-clock deadlines that ignore process/loop freeze time.

When the OS suspends the process or a blocking call freezes the event loop,
plain ``monotonic() - started`` deadlines falsely expire.  Active
:class:`SuspendAwareDeadline` instances registered here are credited back
when the out-of-loop watchdog detects a suspend, and individual poll loops
credit per-sleep overruns via :meth:`SuspendAwareDeadline.credit_poll_sleep`.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

__all__ = [
    'SuspendAwareDeadline',
    'credit_active_deadlines_process_suspend',
    'register_deadline',
    'unregister_deadline',
]

_active: list[SuspendAwareDeadline] = []
_lock = threading.Lock()


@dataclass
class SuspendAwareDeadline:
    """Budget in seconds of *active* runtime; frozen wall-clock is discounted."""

    budget_seconds: float
    poll_interval: float = 0.5
    freeze_grace_seconds: float = 30.0
    _started: float = field(default_factory=time.monotonic, init=False)

    def __post_init__(self) -> None:
        if self.budget_seconds < 0:
            self.budget_seconds = 0.0
        register_deadline(self)

    def close(self) -> None:
        unregister_deadline(self)

    def credit_poll_sleep(self, slept: float) -> float:
        """Credit a poll sleep that overran — loop/process was likely frozen."""
        overrun = slept - self.poll_interval
        if overrun > self.freeze_grace_seconds:
            self._started += overrun
            return overrun
        return 0.0

    def credit_process_suspend(self, frozen_seconds: float) -> None:
        """Credit whole-process suspend reported by the loop watchdog."""
        if frozen_seconds > self.freeze_grace_seconds:
            self._started += frozen_seconds - self.freeze_grace_seconds

    def elapsed(self) -> float:
        return time.monotonic() - self._started

    def expired(self) -> bool:
        if self.budget_seconds <= 0:
            return False
        return self.elapsed() > self.budget_seconds

    def remaining(self) -> float:
        if self.budget_seconds <= 0:
            return float('inf')
        return max(0.0, self.budget_seconds - self.elapsed())


def register_deadline(deadline: SuspendAwareDeadline) -> None:
    with _lock:
        if deadline not in _active:
            _active.append(deadline)


def unregister_deadline(deadline: SuspendAwareDeadline) -> None:
    with _lock:
        try:
            _active.remove(deadline)
        except ValueError:
            pass


def credit_active_deadlines_process_suspend(frozen_seconds: float) -> None:
    """Credit every active deadline after a PROCESS_SUSPEND event."""
    with _lock:
        deadlines = list(_active)
    for deadline in deadlines:
        deadline.credit_process_suspend(frozen_seconds)
