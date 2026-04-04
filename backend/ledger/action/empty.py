"""Placeholder action used when no operation is required."""

from dataclasses import dataclass
from typing import ClassVar

from backend.core.schemas import ActionType
from backend.ledger.action.action import Action


@dataclass
class NullAction(Action):
    """An action that does nothing."""

    action: ClassVar[str] = ActionType.NULL

    @property
    def message(self) -> str:
        """Get null action message."""
        return 'No action'
