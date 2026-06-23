"""Idle-output detach thresholds derived from command wall-clock budgets.

Foreground shell commands use idle-output detection before detaching to a
background session.  The idle window scales with the action's hard timeout so
long, legitimately quiet work (test suites, compiles) is not detached after
30s while still allowing detach on true hangs.
"""

from __future__ import annotations

from backend.execution.runtime_mixins.command_timeout import SAFETY_NET_TIMEOUT

# Share of an agent-specified timeout reserved for quiet phases after output.
_IDLE_EXPLICIT_FRACTION = 0.5
_IDLE_EXPLICIT_CAP_SECONDS = 180.0

# Modest scaling when the runtime applies the default safety-net hard limit.
_IDLE_SAFETY_NET_FRACTION = 0.15
_IDLE_SAFETY_NET_CAP_SECONDS = 90.0

# Slow-start grace before the first output byte (cold starts, package downloads).
_IDLE_INITIAL_FRACTION = 0.25
_IDLE_INITIAL_CAP_SECONDS = 120.0


def compute_idle_detach_timeouts(
    hard_limit_seconds: float | int | None,
    *,
    base_idle_seconds: int = 30,
    blocking: bool = False,
) -> tuple[float, float, float]:
    """Return ``(hard_limit, idle_after_output, initial_grace)`` in seconds.

    * *idle_after_output* — max silence after the first output byte before detach.
    * *initial_grace* — max silence before any output before detach.
    """
    hard_limit = float(hard_limit_seconds or SAFETY_NET_TIMEOUT)
    base_idle = float(base_idle_seconds)

    if hard_limit < float(SAFETY_NET_TIMEOUT):
        idle_timeout = max(
            base_idle,
            min(hard_limit * _IDLE_EXPLICIT_FRACTION, _IDLE_EXPLICIT_CAP_SECONDS),
        )
    else:
        idle_timeout = max(
            base_idle,
            min(
                hard_limit * _IDLE_SAFETY_NET_FRACTION,
                _IDLE_SAFETY_NET_CAP_SECONDS,
            ),
        )

    if blocking:
        idle_timeout = min(hard_limit * 0.9, idle_timeout * 2.0)

    initial_grace = max(
        idle_timeout * 2.0,
        min(hard_limit * _IDLE_INITIAL_FRACTION, _IDLE_INITIAL_CAP_SECONDS),
    )
    initial_grace = min(initial_grace, hard_limit * 0.9)

    return hard_limit, idle_timeout, initial_grace


__all__ = ['compute_idle_detach_timeouts']
