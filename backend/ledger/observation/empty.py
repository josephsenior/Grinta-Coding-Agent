"""Placeholder observation used when no data is produced."""

from dataclasses import dataclass
from typing import ClassVar

from backend.core.schemas import ObservationType
from backend.ledger.observation.observation import Observation


@dataclass
class NullObservation(Observation):
    """This data class represents a null observation.

    This is used when the produced action is NOT executable.
    """

    observation: ClassVar[str] = ObservationType.NULL

    @property
    def message(self) -> str:
        """Get null observation message."""
        return "No observation"

