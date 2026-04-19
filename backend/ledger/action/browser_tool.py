"""Action for native in-process browser automation (browser-use library)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from backend.core.enums import ActionConfirmationStatus, ActionSecurityRisk
from backend.core.schemas import ActionType
from backend.ledger.action.action import Action


@dataclass
class BrowserToolAction(Action):
    """One browser tool invocation (navigate, snapshot, click, etc.).

    The orchestrator LLM is the only policy; this does not wrap browser_use.Agent.
    """

    command: str = ''
    params: dict[str, Any] = field(default_factory=dict)
    thought: str = ''

    action: ClassVar[str] = ActionType.BROWSER_TOOL
    runnable: ClassVar[bool] = True
    confirmation_state: ActionConfirmationStatus = ActionConfirmationStatus.CONFIRMED
    security_risk: ActionSecurityRisk = ActionSecurityRisk.HIGH

    @property
    def message(self) -> str:
        return f'Browser: {self.command}'
