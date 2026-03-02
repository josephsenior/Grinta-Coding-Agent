"""Action type for proactive circuit-breaker progress signalling."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from backend.core.enums import ActionConfirmationStatus, ActionSecurityRisk, ActionType
from backend.events.action.action import Action


@dataclass
class SignalProgressAction(Action):
    """Signal to the controller that deliberate forward progress is being made.

    Calling this action partially resets the circuit breaker's stuck-detection
    counter so long-running but healthy tasks are not falsely interrupted.

    The LLM should call this every 10-15 steps during large multi-file tasks,
    migrations, or other sustained sequential operations.
    """

    progress_note: str = ""  # What was just done and what's next

    action: ClassVar[str] = ActionType.SIGNAL_PROGRESS
    runnable: ClassVar[bool] = True
    confirmation_state: ActionConfirmationStatus = ActionConfirmationStatus.CONFIRMED
    security_risk: ActionSecurityRisk = ActionSecurityRisk.LOW

    @property
    def message(self) -> str:
        note = self.progress_note[:100] or "(no note)"
        return f"SignalProgress: {note}"

    def __str__(self) -> str:
        return f"**SignalProgressAction**\nNOTE:\n{self.progress_note}"

    __test__ = False
