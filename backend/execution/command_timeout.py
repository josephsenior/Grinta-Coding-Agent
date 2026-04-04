"""Command timeout configuration for Runtime action execution.

All commands run non-blocking with no hard wall-clock timeout by default.
The runtime's idle-output detection (NO_CHANGE_TIMEOUT_SECONDS = 30s)
handles commands that finish or hang — no pattern matching required.
A generous safety-net hard timeout prevents truly pathological hangs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.ledger.action import Action

# Safety-net hard timeout for all commands (seconds).
# The idle-output timeout (30s no change) handles normal completion.
# This only fires for commands that keep producing output forever
# without the shell prompt returning (e.g. infinite log tailing).
_SAFETY_NET_TIMEOUT: int = 600


class CommandTimeoutMixin:
    """Mixin providing command timeout configuration for Runtime subclasses."""

    sid: str
    config: Any
    process_manager: Any

    def _set_action_timeout(self, event: Action) -> None:
        """Set timeout for action: no hard timeout, non-blocking.

        All commands run without a hard wall-clock timeout so that slow
        operations (npm install, prisma generate, cargo build, etc.) are
        never killed prematurely.  The runtime's idle-output detection
        (30 s with no new output) handles completion/hang detection.

        A generous safety-net timeout (_SAFETY_NET_TIMEOUT) catches
        pathological cases where a command keeps emitting output forever.

        Args:
            event: Action to set timeout for
        """
        from backend.ledger.action import CmdRunAction

        if event.timeout is not None:
            return

        if isinstance(event, CmdRunAction):
            event.set_hard_timeout(_SAFETY_NET_TIMEOUT, blocking=False)
        else:
            event.set_hard_timeout(self.config.runtime_config.timeout, blocking=False)
