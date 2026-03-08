"""Action types for interacting with generic terminal (PTY) sessions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from backend.core.enums import ActionConfirmationStatus, ActionSecurityRisk
from backend.core.schemas import ActionType
from backend.events.action.action import Action


@dataclass
class TerminalRunAction(Action):
    """Action to start a new terminal session."""

    command: str = ""
    cwd: str | None = None
    action: ClassVar[str] = ActionType.TERMINAL_RUN
    runnable: ClassVar[bool] = True
    confirmation_state: ActionConfirmationStatus = ActionConfirmationStatus.CONFIRMED
    security_risk: ActionSecurityRisk = ActionSecurityRisk.UNKNOWN

    @property
    def message(self) -> str:
        """Get command execution message."""
        return f"Starting terminal session with command: {self.command}"

    def __str__(self) -> str:
        """Return a readable summary."""
        return f"**TerminalRunAction**\nCOMMAND:\n{self.command}"



@dataclass
class TerminalInputAction(Action):
    """Action to send input to an existing terminal session."""

    session_id: str = ""
    input: str = ""
    is_control: bool = False
    action: ClassVar[str] = ActionType.TERMINAL_INPUT
    runnable: ClassVar[bool] = True
    confirmation_state: ActionConfirmationStatus = ActionConfirmationStatus.CONFIRMED
    security_risk: ActionSecurityRisk = ActionSecurityRisk.UNKNOWN

    @property
    def message(self) -> str:
        """Get input message."""
        if self.is_control:
            return f"Sending control {self.input!r} to terminal {self.session_id}"
        return f"Sending input to terminal {self.session_id}"

    def __str__(self) -> str:
        """Return a readable summary."""
        return f"**TerminalInputAction (session={self.session_id}, is_control={self.is_control})**\nINPUT:\n{self.input}"



@dataclass
class TerminalReadAction(Action):
    """Action to read the output buffer of an existing terminal session."""

    session_id: str = ""
    action: ClassVar[str] = ActionType.TERMINAL_READ
    runnable: ClassVar[bool] = True
    confirmation_state: ActionConfirmationStatus = ActionConfirmationStatus.CONFIRMED
    security_risk: ActionSecurityRisk = ActionSecurityRisk.UNKNOWN

    @property
    def message(self) -> str:
        """Get read message."""
        return f"Reading from terminal {self.session_id}"

    def __str__(self) -> str:
        """Return a readable summary."""
        return f"**TerminalReadAction (session={self.session_id})**"

