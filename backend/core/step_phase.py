"""Current agent-step phase breadcrumb for stall diagnostics.

Updated by :meth:`SessionOrchestrator._step_inner` at each major stage so the
out-of-loop watchdog can report *where* the agent was when the event loop
stopped turning — without requiring DEBUG logging or reading full stack traces.
"""

from __future__ import annotations

import threading

__all__ = ['clear_step_phase', 'get_step_phase', 'set_step_phase']

_lock = threading.Lock()
_phase: str = 'idle'


def set_step_phase(phase: str) -> None:
    """Record the current high-level step phase (thread-safe)."""
    with _lock:
        global _phase  # noqa: PLW0603
        _phase = phase.strip() or 'unknown'


def get_step_phase() -> str:
    """Return the last recorded step phase."""
    with _lock:
        return _phase


def clear_step_phase() -> None:
    """Reset to idle (call when no step is in flight)."""
    set_step_phase('idle')
