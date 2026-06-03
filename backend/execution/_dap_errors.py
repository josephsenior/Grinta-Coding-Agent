"""DAP exception hierarchy.

Extracted from backend/execution/debugger.py to keep the parent module
under the per-file LOC budget. ``DAPError`` is the base for all DAP
communication errors; ``DAPStartPhaseError`` adds a startup-phase
tag used by the manager to surface which DAP lifecycle step failed.
"""

from __future__ import annotations


class DAPError(RuntimeError):
    """Raised when DAP communication fails."""


class DAPStartPhaseError(DAPError):
    """Debugger start failed during a specific startup phase."""

    def __init__(
        self, phase: str, detail: str, *, timeout: float | None = None
    ) -> None:
        self.phase = phase
        self.timeout = timeout
        timeout_msg = f' after {timeout:.1f}s' if timeout and timeout > 0 else ''
        super().__init__(f'debugger start failed during {phase}{timeout_msg}: {detail}')
