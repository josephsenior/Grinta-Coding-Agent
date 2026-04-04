"""Observation representing successful completion of an action."""

from dataclasses import dataclass
from typing import ClassVar

from backend.core.schemas import ObservationType
from backend.ledger.observation.observation import Observation


@dataclass
class SuccessObservation(Observation):
    """This data class represents the result of a successful action."""

    observation: ClassVar[str] = ObservationType.SUCCESS

    @property
    def message(self) -> str:
        """Get success message content."""
        return self.content
