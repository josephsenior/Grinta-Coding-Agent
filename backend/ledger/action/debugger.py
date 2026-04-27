"""Action type for Python DAP/debugpy debugger sessions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from backend.core.enums import ActionConfirmationStatus, ActionSecurityRisk
from backend.core.schemas import ActionType
from backend.ledger.action.action import Action


@dataclass
class DebuggerAction(Action):
    """Action to control a stateful Python debugger session."""

    debug_action: str = ''
    session_id: str | None = None
    program: str | None = None
    cwd: str | None = None
    args: list[str] = field(default_factory=list)
    breakpoints: list[dict[str, Any]] = field(default_factory=list)
    file: str | None = None
    lines: list[int] = field(default_factory=list)
    thread_id: int | None = None
    frame_id: int | None = None
    variables_reference: int | None = None
    expression: str | None = None
    count: int | None = None
    stop_on_entry: bool = False
    just_my_code: bool = False
    python: str | None = None
    timeout: float | None = None
    action: ClassVar[str] = ActionType.DEBUGGER
    runnable: ClassVar[bool] = True
    confirmation_state: ActionConfirmationStatus = ActionConfirmationStatus.CONFIRMED
    security_risk: ActionSecurityRisk = ActionSecurityRisk.UNKNOWN

    @property
    def message(self) -> str:
        """Get a concise debugger action message."""
        target = self.session_id or self.program or ''
        return f'Python debugger {self.debug_action}: {target}'

    def __str__(self) -> str:
        """Return a readable summary."""
        return (
            f'**DebuggerAction ({self.debug_action}, session={self.session_id})**\n'
            f'PROGRAM: {self.program or ""}'
        )
