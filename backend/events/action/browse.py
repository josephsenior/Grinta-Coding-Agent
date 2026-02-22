"""Action types for interactive browsing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from backend.core.enums import ActionConfirmationStatus, ActionSecurityRisk
from backend.core.schemas import ActionType
from backend.events.action.action import Action


@dataclass
class BrowseInteractiveAction(Action):
    """Action to perform interactive browser operations.

    This is a higher-level browsing action that can encode one or more
    browser interactions (clicks, typing, navigation) for an external
    browser tool/runtime.
    """

    browser_actions: str = ""
    thought: str = ""

    action: ClassVar[str] = ActionType.BROWSE_INTERACTIVE
    runnable: ClassVar[bool] = True

    confirmation_state: ActionConfirmationStatus = ActionConfirmationStatus.CONFIRMED
    security_risk: ActionSecurityRisk = ActionSecurityRisk.UNKNOWN

    @property
    def message(self) -> str:
        return "Running interactive browser actions"

    __test__ = False
