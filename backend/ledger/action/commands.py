"""Action types for executing shell commands."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from backend.core.enums import ActionConfirmationStatus, ActionSecurityRisk
from backend.core.schemas import ActionType
from backend.ledger.action.action import Action


@dataclass
class CmdRunAction(Action):
    """Action to run a shell command.

    Attributes:
        command: Shell command to execute
        is_input: Whether command is user input (for stdin)
        thought: Agent's reasoning for this action
        blocking: Whether to wait for command to complete
        is_static: Whether command is static (from static analysis)
        cwd: Working directory for command
        hidden: Whether to hide command from user

    """

    command: str = ''
    is_input: bool = False
    thought: str = ''
    blocking: bool = False
    is_static: bool = False
    cwd: str | None = None
    hidden: bool = False
    #: When set, the CLI renders this friendly label as an activity row instead of
    #: showing the raw shell command in a terminal block.  Only LLM-generated
    #: commands (execute_bash / execute_powershell) leave this empty.
    display_label: str = ''
    stdin: str | None = None
    is_background: bool = False
    truncation_strategy: str | None = None
    grep_pattern: str | None = None
    action: ClassVar[str] = ActionType.RUN
    runnable: ClassVar[bool] = True
    confirmation_state: ActionConfirmationStatus = ActionConfirmationStatus.CONFIRMED
    security_risk: ActionSecurityRisk = ActionSecurityRisk.UNKNOWN

    @property
    def message(self) -> str:
        """Get command execution message."""
        return f'Running command: {self.command}'

    def __str__(self) -> str:
        """Return a readable summary including command metadata."""
        ret = f'**CmdRunAction (source={self.source}, is_input={self.is_input})**\n'
        if self.thought:
            ret += f'THOUGHT: {self.thought}\n'
        ret += f'COMMAND:\n{self.command}'
        return ret
