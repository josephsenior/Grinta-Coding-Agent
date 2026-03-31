"""Event system for agent actions and observations.

Classes:
    ActionConfirmationStatus
    ActionSecurityRisk
    Action
"""

from dataclasses import dataclass, field
from typing import ClassVar

from backend._canonical import CanonicalMeta
from backend.core.schemas import (
    ActionConfirmationStatus,
)
from backend.ledger.event import Event


@dataclass
class Action(Event, metaclass=CanonicalMeta):
    """Base class for all agent actions.

    Actions represent things the agent wants to do (edit files, run commands, etc.).
    They are executed by the runtime and produce Observations.
    """

    action: ClassVar[str] = ""
    runnable: ClassVar[bool] = False
    __test__: ClassVar[bool] = False

    # Declared as a proper field so subclass __post_init__ chains are safe.
    confirmation_state: ActionConfirmationStatus = field(
        default=ActionConfirmationStatus.CONFIRMED, init=False
    )

    def __post_init__(self) -> None:
        # Ensure confirmation_state always has a value (idempotent with field default)
        if not hasattr(self, "confirmation_state"):
            self.confirmation_state = ActionConfirmationStatus.CONFIRMED


__all__ = ["Action", "ActionConfirmationStatus"]
