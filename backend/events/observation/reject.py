"""Observation emitted when the user rejects an agent action."""

from dataclasses import dataclass
from typing import ClassVar

from backend.core.schemas import ObservationType
from backend.events.observation.observation import Observation


@dataclass
class UserRejectObservation(Observation):
    """This data class represents the result of a rejected action."""

    observation: ClassVar[str] = ObservationType.USER_REJECTED

    @property
    def message(self) -> str:
        """Get rejection reason message."""
        return self.content

